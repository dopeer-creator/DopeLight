"""Model downloads into <data>/models: resumable, cancellable, with progress.

Layout:
    models/hf/     Hugging Face cache (weights)
    models/code/   model source code from GitHub, one folder per pinned commit
    models/ready/  one marker file per fully downloaded model
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from relight_backend.models.specs import GithubCode, HfWeights, ModelSpec
from relight_backend.utils.paths import models_dir

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]  # (bytes done, bytes total)
CancelCheck = Callable[[], None]  # raises to cancel

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelFiles:
    weights: Path
    code: Path | None


def _hf_cache() -> Path:
    return models_dir() / "hf"


def _repo_cache(weights: HfWeights) -> Path:
    return _hf_cache() / f"models--{weights.repo_id.replace('/', '--')}"


def weights_path(weights: HfWeights) -> Path:
    """Snapshot folder in the Hugging Face cache layout."""
    return _repo_cache(weights) / "snapshots" / weights.revision


def code_path(code: GithubCode) -> Path:
    return models_dir() / "code" / f"{code.repo.split('/')[-1]}-{code.commit[:12]}"


def _marker(spec: ModelSpec) -> Path:
    return models_dir() / "ready" / f"{spec.key}.ok"


def is_ready(spec: ModelSpec) -> bool:
    """True when every file of the model is on disk (works offline)."""
    return (
        _marker(spec).exists()
        and weights_path(spec.weights).is_dir()
        and (spec.code is None or code_path(spec.code).is_dir())
    )


def local_files(spec: ModelSpec) -> ModelFiles:
    return ModelFiles(
        weights=weights_path(spec.weights),
        code=code_path(spec.code) if spec.code else None,
    )


def _fetch_command(command: str, weights: HfWeights) -> list[str]:
    return [
        sys.executable, "-m", "relight_backend.utils.fetch_weights", command,
        weights.repo_id, weights.revision, str(_hf_cache()), *weights.allow_patterns,
    ]


def _download_weights(weights: HfWeights, progress: ProgressFn, check_cancel: CancelCheck) -> None:
    sized = subprocess.run(
        _fetch_command("size", weights), capture_output=True, text=True, creationflags=_NO_WINDOW
    )
    if sized.returncode != 0:
        raise DownloadError(
            f"Could not reach Hugging Face for {weights.repo_id}: {sized.stderr.strip()[-400:]}"
        )
    total = int(sized.stdout.strip().splitlines()[-1])

    # stderr goes to a file, not a pipe: nobody reads it while the download
    # runs, and a full pipe would block the child.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errors:
        process = subprocess.Popen(
            _fetch_command("download", weights),
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            creationflags=_NO_WINDOW,
        )
        written = [0]
        reader = threading.Thread(target=_read_progress, args=(process, written), daemon=True)
        reader.start()
        try:
            while process.poll() is None:
                progress(min(written[0], total), total)
                check_cancel()
                time.sleep(0.5)
        except BaseException:
            process.kill()
            process.wait()
            raise
        if process.returncode != 0:
            errors.seek(0)
            raise DownloadError(
                f"Download of {weights.repo_id} failed: {errors.read().strip()[-400:]}"
            )
    progress(total, total)


def _read_progress(process: subprocess.Popen[str], written: list[int]) -> None:
    """Collect "PROGRESS <bytes>" lines printed by the fetch process."""
    if process.stdout is None:
        return
    for line in process.stdout:
        label, _, value = line.strip().partition(" ")
        if label == "PROGRESS" and value.isdigit():
            written[0] = int(value)


def _download_code(code: GithubCode) -> None:
    target = code_path(code)
    if target.is_dir():
        return
    base = f"https://raw.githubusercontent.com/{code.repo}/{code.commit}"
    log.info("downloading model code from %s", base)

    # Fetch into a staging folder and rename at the end, so a half-finished
    # download is never mistaken for a complete one.
    staging = target.with_name(target.name + ".tmp")
    shutil.rmtree(staging, ignore_errors=True)
    for name in code.files:
        destination = staging / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(f"{base}/{name}", timeout=60) as response:
                destination.write_bytes(response.read())
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise DownloadError(f"Could not download {base}/{name}: {exc}") from exc
    staging.rename(target)


def ensure(spec: ModelSpec, progress: ProgressFn, check_cancel: CancelCheck) -> ModelFiles:
    """Make sure the model is on disk, downloading what is missing."""
    if not is_ready(spec):
        log.info("downloading %s (~%d MB)", spec.title, spec.approx_size_mb)
        _download_weights(spec.weights, progress, check_cancel)
        if spec.code is not None:
            _download_code(spec.code)
        marker = _marker(spec)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(spec.weights.revision, encoding="utf-8")
    return local_files(spec)
