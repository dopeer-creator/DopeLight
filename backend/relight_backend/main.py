"""FastAPI app and entry point.

Run: python -m relight_backend.main --port 8765   (token in RELIGHT_TOKEN)

Model code (PyTorch and friends) is imported inside job functions, not at the
top, so the server answers /health within a second of starting.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import secrets
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from relight_backend.constants import APP_NAME, APP_VERSION, HOST, TOKEN_ENV
from relight_backend.jobs import Job, JobManager
from relight_backend.models import specs
from relight_backend.pipeline.sessions import MAP_NAMES, SessionStore, map_file
from relight_backend.utils import downloads
from relight_backend.utils.logging_setup import setup_logging
from relight_backend.utils.paths import sessions_dir
from relight_backend.utils.vram import gpu_info

log = logging.getLogger(__name__)

# Seconds to wait for a clean shutdown before forcing the process to exit.
FORCE_EXIT_AFTER = 3.0
_MB = 1024 * 1024


class GpuStatus(BaseModel):
    available: bool
    name: str | None
    vram_total_mb: int | None
    vram_free_mb: int | None
    source: str


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    gpu: GpuStatus
    models: dict[str, bool]


class EnsureRequest(BaseModel):
    models: list[str] | None = None  # None = every model


class JobStarted(BaseModel):
    job_id: str


class ExportRequest(BaseModel):
    lights: list[dict[str, Any]]
    globals: dict[str, float]
    kind: Literal["relit", "light_layer", "per_light"] = "relit"
    format: Literal["png", "jpeg", "tiff"] = "png"
    bit_depth: Literal[8, 16] = 8
    quality: int = Field(92, ge=1, le=100)
    blend: Literal["normal", "linear"] = "normal"
    alpha: bool = False
    target: str  # full path of the main file to write


class SessionResponse(BaseModel):
    session_id: str
    cached: bool  # True when the maps were already on disk; then job_id is None
    job_id: str | None
    maps: dict[str, str]


def _map_urls(session_id: str) -> dict[str, str]:
    return {name: f"/session/{session_id}/{name}" for name in MAP_NAMES}


def _is_complete(store: SessionStore, session_id: str, normals: str) -> bool:
    meta = store.load_meta(session_id)
    folder = store.folder(session_id)
    if meta is None or folder is None or meta.normals_method != normals:
        return False
    return all((folder / map_file(name, normals)).exists() for name in MAP_NAMES)


def _sse(job: Job) -> Iterator[str]:
    for event in job.stream():
        yield f"data: {json.dumps(event)}\n\n"


def create_app(token: str, data_root: Path | None = None) -> FastAPI:
    app = FastAPI(title=APP_NAME, version=APP_VERSION)
    store = SessionStore(data_root or sessions_dir())
    jobs = JobManager()

    # The renderer's origin differs between dev (http://localhost) and the
    # packaged app (file://), so any origin may call; the token is the gate.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    bearer = HTTPBearer(auto_error=False)

    def require_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),  # noqa: B008
    ) -> None:
        if credentials is None or not secrets.compare_digest(credentials.credentials, token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or wrong auth token")

    protected = [Depends(require_token)]

    def find_job(job_id: str) -> Job:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
        return job

    @app.get("/health", dependencies=protected)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            app=APP_NAME,
            version=APP_VERSION,
            gpu=GpuStatus(**asdict(gpu_info())),
            models={spec.key: downloads.is_ready(spec) for spec in specs.ALL},
        )

    @app.post("/models/ensure", dependencies=protected)
    def ensure_models(request: EnsureRequest) -> JobStarted:
        keys = request.models if request.models is not None else list(specs.BY_KEY)
        unknown = [key for key in keys if key not in specs.BY_KEY]
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown models: {unknown}")

        def work(job: Job) -> dict[str, Any]:
            for index, key in enumerate(keys):
                spec = specs.BY_KEY[key]

                def on_progress(done: int, total: int, spec: specs.ModelSpec = spec,
                                index: int = index) -> None:
                    fraction = (index + (done / total if total else 0.0)) / len(keys)
                    job.report("download", fraction, f"Downloading {spec.title}", model=spec.key,
                               download_done_mb=done // _MB, download_total_mb=total // _MB)

                downloads.ensure(spec, on_progress, job.check_cancel)
            return {"models": keys}

        return JobStarted(job_id=jobs.submit("models", work).id)

    @app.post("/session", dependencies=protected)
    async def create_session(
        file: UploadFile = File(...),  # noqa: B008
        normals: str = Form(specs.DEFAULT_NORMALS),
    ) -> SessionResponse:
        if normals not in specs.NORMALS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"normals must be one of {list(specs.NORMALS)}"
            )
        data = await file.read()
        try:
            Image.open(io.BytesIO(data)).verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a readable image file") from exc

        session_id = store.create(data)
        if _is_complete(store, session_id, normals):
            return SessionResponse(
                session_id=session_id, cached=True, job_id=None, maps=_map_urls(session_id)
            )

        source_name = file.filename or "image"

        def work(job: Job) -> dict[str, Any]:
            from relight_backend.pipeline.preprocess import PreprocessOptions, preprocess

            meta = preprocess(store, session_id, source_name, PreprocessOptions(normals), job)
            return asdict(meta)

        job = jobs.submit("preprocess", work)
        return SessionResponse(
            session_id=session_id, cached=False, job_id=job.id, maps=_map_urls(session_id)
        )

    @app.get("/session/{session_id}", dependencies=protected)
    def session_info(session_id: str) -> dict[str, Any]:
        meta = store.load_meta(session_id)
        if meta is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session, or not finished yet")
        return asdict(meta)

    @app.get("/session/{session_id}/depth_raw", dependencies=protected)
    def session_depth_raw(session_id: str) -> Response:
        """Depth as raw little-endian uint16, row by row, at the session's working size.

        The live preview uses this instead of depth.png: browsers decode 16-bit
        PNGs to 8 bits, which would band the heightfield and its shadows.
        """
        path = store.map_path(session_id, "depth")
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such map")
        from relight_backend.utils.image_io import load_gray16_bytes

        return Response(load_gray16_bytes(path), media_type="application/octet-stream")

    @app.get("/session/{session_id}/{map_name}", dependencies=protected)
    def session_map(session_id: str, map_name: str) -> FileResponse:
        path = store.map_path(session_id, map_name)
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such map")
        return FileResponse(path, media_type="image/png")

    @app.post("/session/{session_id}/export", dependencies=protected)
    def export_session(session_id: str, request: ExportRequest) -> JobStarted:
        """Render at full resolution and write files next to `target`. See pipeline/export.py."""
        if store.load_meta(session_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such session, or not finished yet")
        target = Path(request.target)
        if not target.is_absolute() or not target.parent.is_dir():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "The folder to save into does not exist"
            )

        def work(job: Job) -> dict[str, Any]:
            from relight_backend.pipeline.export import ExportOptions, export
            from relight_backend.pipeline.shading import GlobalSettings, Light

            options = ExportOptions(
                kind=request.kind, format=request.format, bit_depth=request.bit_depth,
                quality=request.quality, blend=request.blend, alpha=request.alpha,
            )
            lights = [Light.from_json(entry) for entry in request.lights]
            settings = GlobalSettings.from_json(request.globals)
            files = export(store, session_id, lights, settings, options, target, job)
            return {"files": [str(path) for path in files]}

        return JobStarted(job_id=jobs.submit("export", work).id)

    @app.get("/jobs/{job_id}", dependencies=protected)
    def job_status(job_id: str) -> dict[str, Any]:
        return find_job(job_id).snapshot()

    @app.get("/jobs/{job_id}/events", dependencies=protected)
    def job_events(job_id: str) -> StreamingResponse:
        """Server-sent events: every progress event so far, then live ones until the job ends."""
        return StreamingResponse(_sse(find_job(job_id)), media_type="text/event-stream")

    @app.post("/jobs/{job_id}/cancel", dependencies=protected)
    def job_cancel(job_id: str) -> dict[str, Any]:
        job = find_job(job_id)
        job.cancel()
        return job.snapshot()

    @app.post("/unload", dependencies=protected)
    def unload() -> dict[str, str]:
        """Free VRAM. Preprocess models already unload after each use."""
        if "torch" in sys.modules:
            from relight_backend.utils.device import release_memory

            release_memory()
        return {"status": "ok"}

    return app


def _wait_for_process_exit(pid: int) -> None:
    """Block until the process with this id has ended."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        synchronize, infinite = 0x00100000, 0xFFFFFFFF
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if handle:  # no handle means it is already gone
            kernel32.WaitForSingleObject(handle, infinite)
            kernel32.CloseHandle(handle)
    else:
        while os.getppid() == pid:
            time.sleep(1.0)


def _exit_when_parent_exits(server: uvicorn.Server, parent_pid: int) -> None:
    """Stop the server when the desktop app goes away, however it ended.

    This waits on the parent's process handle. An earlier version watched for
    stdin closing instead; on Windows a thread blocked reading the stdin pipe
    made `import torch` hang in other threads, so stdin is left alone.
    """
    _wait_for_process_exit(parent_pid)
    log.info("parent process %d is gone; shutting down", parent_pid)
    server.should_exit = True
    threading.Timer(FORCE_EXIT_AFTER, lambda: os._exit(0)).start()


def main() -> None:
    parser = argparse.ArgumentParser(prog="relight_backend")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument(
        "--parent-pid",
        type=int,
        help="shut down when this process exits (the desktop app passes its own id)",
    )
    args = parser.parse_args()

    setup_logging()
    # No telemetry, and no network use by the model libraries: downloads happen
    # only in the separate fetch process (utils/fetch_weights.py).
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    token = os.environ.get(TOKEN_ENV)
    if not token:
        sys.exit(f"{TOKEN_ENV} is not set; refusing to start without an auth token")

    config = uvicorn.Config(create_app(token), host=HOST, port=args.port, log_config=None)
    server = uvicorn.Server(config)

    if args.parent_pid is not None:
        threading.Thread(
            target=_exit_when_parent_exits, args=(server, args.parent_pid), daemon=True
        ).start()

    log.info("starting %s backend on %s:%d", APP_NAME, HOST, args.port)
    server.run()


if __name__ == "__main__":
    main()
