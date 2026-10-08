"""Photoreal render of one photo with one scene of lights, without the app window.

    node scripts/uv.mjs run --no-sync --directory backend python ../scripts/render_scene.py \
        ../samples/fighter.jpg ../docs/scenes/fighter-yellow-top-red-trim.json ../render-out/fighter

Paths are relative to `backend/`. Options after the three paths: `--long-edge 768`,
`--steps 25`, `--adherence 0.5`, `--no-highres`, and `--preview-only`: no AI
model, only the preview's own shading at the working size, written as
`shading.png` in a second or two. That is the quick way to judge a change to
the shading (shadows, rim light, falloff).

Preprocesses the photo (cached after the first time), downloads the photoreal
models if they are missing (3.7 GB), renders, and writes into the out folder:
`hint.jpg` (the preview's shading), `diffusion.jpg` (the raw model output),
`preview.jpg` (the light applied to the photo: the result), `sheet.jpg` (all
of them next to the original), and `meta.json` (time, device, peak VRAM).

It is for judging the look and for measuring on the GPU. A scene file is what
the app's RELIGHT_SCENE takes: `{"lights": [...], "globals": {...}}`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from relight_backend.pipeline import photoreal  # noqa: E402
from relight_backend.pipeline.preprocess import PreprocessOptions, preprocess  # noqa: E402
from relight_backend.pipeline.sessions import SessionStore  # noqa: E402
from relight_backend.pipeline.shading import GlobalSettings, Light  # noqa: E402
from relight_backend.utils.paths import sessions_dir  # noqa: E402

DEFAULT_GLOBALS = {"ambient": 0, "exposure": 0, "keepOriginalLight": 1, "smoothing": 0.3,
                   "flatten": 0.5}
SHEET_HEIGHT = 720
STARTED = time.perf_counter()


class Console:
    """Prints each new progress message once, with the time since the start."""

    last = ""

    def report(self, stage: str, progress: float, message: str = "", **extra: Any) -> None:
        if message and message != Console.last:
            megabytes = extra.get("download_total_mb")
            suffix = f" ({megabytes} MB)" if megabytes else ""
            print(f"  [{time.perf_counter() - STARTED:6.1f}s] {message}{suffix}", flush=True)
        Console.last = message

    def check_cancel(self) -> None:
        pass


def sheet(tiles: list[tuple[str, Path]], out: Path) -> None:
    images = []
    for label, path in tiles:
        image = Image.open(path).convert("RGB")
        width = round(image.width * SHEET_HEIGHT / image.height)
        image = image.resize((width, SHEET_HEIGHT), Image.Resampling.LANCZOS)
        ImageDraw.Draw(image).text((8, 6), label, fill=(255, 255, 255), stroke_width=2,
                                   stroke_fill=(0, 0, 0))
        images.append(image)
    page = Image.new("RGB", (sum(image.width for image in images), SHEET_HEIGHT))
    x = 0
    for image in images:
        page.paste(image, (x, 0))
        x += image.width
    page.save(out, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("scene", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--long-edge", type=int, default=photoreal.RenderOptions.long_edge)
    parser.add_argument("--steps", type=int, default=photoreal.RenderOptions.steps)
    parser.add_argument("--adherence", type=float, default=photoreal.RenderOptions.adherence)
    parser.add_argument("--no-highres", action="store_true")
    parser.add_argument("--preview-only", action="store_true")
    args = parser.parse_args()

    scene = json.loads(args.scene.read_text(encoding="utf-8"))
    lights = [Light.from_json(entry) for entry in scene["lights"]]
    settings = GlobalSettings.from_json({**DEFAULT_GLOBALS, **scene.get("globals", {})})

    store = SessionStore(sessions_dir())
    session_id = store.create(args.image.read_bytes())
    meta = preprocess(store, session_id, args.image.name, PreprocessOptions(), Console())
    print(f"session {session_id}: original {meta.original_size}, working {meta.working_size}")

    if args.preview_only:
        folder = store.folder(session_id)
        assert folder is not None
        _photo, shading = photoreal.make_hint(folder, meta.normals_method, meta.working_size,
                                              lights, settings)
        args.out.mkdir(parents=True, exist_ok=True)
        shading.save(args.out / "shading.png")
        print("written to", (args.out / "shading.png").resolve())
        return

    options = photoreal.RenderOptions(steps=args.steps, adherence=args.adherence,
                                      long_edge=args.long_edge, highres=not args.no_highres)
    result = photoreal.render(store, session_id, lights, settings, options, Console())
    print(json.dumps({key: result[key] for key in
                      ("diffusion_size", "device", "seconds", "peak_vram_mb", "note")}))

    folder = photoreal.render_folder(store, session_id, result["render_id"])
    assert folder is not None
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ("hint.jpg", "diffusion.jpg", "preview.jpg", "meta.json"):
        shutil.copy(folder / name, args.out / name)
    original = args.out / "original.jpg"
    Image.open(args.image).convert("RGB").save(original, quality=92)
    sheet([("original", original), ("hint (preview shading)", args.out / "hint.jpg"),
           ("raw model output", args.out / "diffusion.jpg"),
           ("result (light applied to the photo)", args.out / "preview.jpg")],
          args.out / "sheet.jpg")
    original.unlink()
    print("written to", args.out.resolve())


if __name__ == "__main__":
    main()
