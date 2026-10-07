"""Benchmark the preprocess pipeline on a folder of images.

    uv run python -m relight_backend.bench --images ../samples --out ../bench-out

For every image and every normals method it writes the maps, a side-by-side
sheet for eyeballing, and report.md / report.json with time and peak VRAM.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from relight_backend.constants import WORKING_LONG_EDGE
from relight_backend.models import specs
from relight_backend.pipeline.preprocess import PreprocessOptions, preprocess
from relight_backend.pipeline.sessions import SessionStore, map_file
from relight_backend.utils.image_io import load_normals
from relight_backend.utils.vram import gpu_info

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SHEET_TILE_HEIGHT = 420


class ConsoleReporter:
    def report(self, stage: str, progress: float, message: str = "", **extra: Any) -> None:
        detail = ""
        if "download_total_mb" in extra:
            detail = f" {extra['download_done_mb']}/{extra['download_total_mb']} MB"
        print(f"    [{progress:4.0%}] {stage}: {message}{detail}", flush=True)

    def check_cancel(self) -> None:
        return None


def axis_agreement(normals_path: Path, reference_path: Path) -> dict[str, float]:
    """Compare a model's normals with depth-derived ones.

    Positive correlation on every axis means the axis convention matches.
    """
    normals, reference = load_normals(normals_path), load_normals(reference_path)
    correlation = [
        float(np.corrcoef(normals[..., axis].ravel(), reference[..., axis].ravel())[0, 1])
        for axis in range(3)
    ]
    cosine = np.clip((normals * reference).sum(axis=-1), -1.0, 1.0)
    return {
        "corr_x": round(correlation[0], 2),
        "corr_y": round(correlation[1], 2),
        "corr_z": round(correlation[2], 2),
        "mean_angle_deg": round(float(np.degrees(np.arccos(cosine)).mean()), 1),
    }


def make_sheet(folder: Path, methods: list[str], target: Path) -> None:
    """Row of labelled tiles: image, mask, depth, then normals per method."""
    tiles = [("image", "albedo_proxy.png"), ("mask", "mask.png"), ("depth", "depth.png")]
    tiles += [(f"normals: {method}", map_file("normal", method)) for method in methods]

    images = []
    for label, name in tiles:
        tile: Image.Image = Image.open(folder / name)
        if tile.mode not in ("RGB", "L"):  # 16-bit depth
            tile = Image.fromarray((np.asarray(tile, dtype=np.float32) / 257.0).astype(np.uint8))
        tile = tile.convert("RGB")
        width = round(tile.width * SHEET_TILE_HEIGHT / tile.height)
        tile = tile.resize((width, SHEET_TILE_HEIGHT), Image.Resampling.LANCZOS)
        ImageDraw.Draw(tile).text((8, 6), label, fill=(255, 255, 255), stroke_width=2,
                                  stroke_fill=(0, 0, 0))
        images.append(tile)

    sheet = Image.new("RGB", (sum(tile.width for tile in images), SHEET_TILE_HEIGHT))
    x = 0
    for tile in images:
        sheet.paste(tile, (x, 0))
        x += tile.width
    sheet.save(target, quality=90)


def run(images: list[Path], out: Path, methods: list[str], working_edge: int) -> dict[str, Any]:
    store = SessionStore(out / "sessions")
    store.root.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"gpu": gpu_info().__dict__, "working_long_edge": working_edge,
                              "images": {}}

    for image in images:
        print(f"\n{image.name}", flush=True)
        session_id = store.create(image.read_bytes())
        folder = store.root / session_id
        stats: dict[str, Any] = {}
        for method in methods:
            print(f"  normals = {method}", flush=True)
            options = PreprocessOptions(normals=method, working_long_edge=working_edge)
            meta = preprocess(store, session_id, image.name, options, ConsoleReporter())
            stats = meta.stats
            working_size = meta.working_size

        agreement = {
            method: axis_agreement(folder / map_file("normal", method),
                                   folder / map_file("normal", "depth"))
            for method in methods
            if method != "depth" and "depth" in methods
        }
        make_sheet(folder, methods, out / f"{image.stem}_sheet.jpg")
        report["images"][image.name] = {
            "working_size": list(working_size), "stats": stats, "vs_depth_normals": agreement,
        }
    return report


def to_markdown(report: dict[str, Any]) -> str:
    gpu = report["gpu"]
    device = gpu["name"] if gpu["available"] else "CPU only (no NVIDIA GPU)"
    lines = [
        "# Preprocess benchmark",
        "",
        f"Device: {device}. Working long edge: {report['working_long_edge']} px.",
        "",
        "| Image | Size | Stage | Model | Load s | Infer s | Peak VRAM MB |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, entry in report["images"].items():
        size = "x".join(str(v) for v in entry["working_size"])
        for stage, stat in entry["stats"].items():
            vram = "n/a (CPU)" if stat["peak_vram_mb"] is None else stat["peak_vram_mb"]
            lines.append(f"| {name} | {size} | {stage} | {stat['model']} | "
                         f"{stat['load_seconds']} | {stat['infer_seconds']} | {vram} |")
    lines += ["", "## Normals vs depth-derived normals", "",
              "Positive correlation on x, y, z means the axis convention matches.", "",
              "| Image | Method | corr x | corr y | corr z | Mean angle (deg) |",
              "| --- | --- | --- | --- | --- | --- |"]
    for name, entry in report["images"].items():
        for method, value in entry["vs_depth_normals"].items():
            lines.append(f"| {name} | {method} | {value['corr_x']} | {value['corr_y']} | "
                         f"{value['corr_z']} | {value['mean_angle_deg']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(prog="relight_backend.bench", description=__doc__)
    parser.add_argument("--images", type=Path, required=True, help="folder of test images")
    parser.add_argument("--out", type=Path, required=True, help="output folder")
    parser.add_argument("--normals", nargs="+", default=list(specs.NORMALS),
                        choices=list(specs.NORMALS))
    parser.add_argument("--working-edge", type=int, default=WORKING_LONG_EDGE)
    parser.add_argument("--fresh", action="store_true", help="delete earlier results first")
    args = parser.parse_args()

    images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        sys.exit(f"No images found in {args.images}")
    if args.fresh:
        shutil.rmtree(args.out, ignore_errors=True)
    args.out.mkdir(parents=True, exist_ok=True)

    report = run(images, args.out, args.normals, args.working_edge)
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = to_markdown(report)
    (args.out / "report.md").write_text(markdown, encoding="utf-8")
    print("\n" + markdown)
    print(f"Sheets and reports are in {args.out.resolve()}")


if __name__ == "__main__":
    main()
