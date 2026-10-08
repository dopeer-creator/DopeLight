"""Preprocess: one image in, mask + depth + normals + albedo proxy out.

Runs once per image. Each model is loaded, used, and unloaded in turn so only
one is ever in VRAM. Maps already on disk are reused.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
import torch
from PIL import Image

from relight_backend.constants import WORKING_LONG_EDGE
from relight_backend.models import specs
from relight_backend.models.base import Model
from relight_backend.pipeline.normals_from_depth import normals_from_depth
from relight_backend.pipeline.sessions import ORIGINAL_FILE, SessionMeta, SessionStore, map_file
from relight_backend.pipeline.shading import thickness_code
from relight_backend.utils import downloads
from relight_backend.utils.device import pick_device, pick_dtype
from relight_backend.utils.image_io import (
    FloatArray,
    load_gray8,
    load_gray16,
    load_image,
    load_normals,
    normalize_vectors,
    resize_long_edge,
    save_aux,
    save_gray8,
    save_gray16,
    save_normals,
)
from relight_backend.utils.vram import track_usage

log = logging.getLogger(__name__)

_MB = 1024 * 1024


class Reporter(Protocol):
    """Progress sink; a `jobs.Job` fits this."""

    def report(self, stage: str, progress: float, message: str = "", **extra: Any) -> None: ...

    def check_cancel(self) -> None: ...


@dataclass(frozen=True)
class PreprocessOptions:
    normals: str = specs.DEFAULT_NORMALS
    working_long_edge: int = WORKING_LONG_EDGE


def model_class(spec: specs.ModelSpec) -> type[Model]:
    """Import the wrapper on demand, so unused models cost nothing."""
    if spec is specs.BIREFNET_LITE:
        from relight_backend.models.birefnet import BiRefNetLite

        return BiRefNetLite
    if spec is specs.DEPTH_ANYTHING_V2_SMALL:
        from relight_backend.models.depth_anything import DepthAnythingV2Small

        return DepthAnythingV2Small
    if spec is specs.DSINE:
        from relight_backend.models.dsine import Dsine

        return Dsine
    if spec is specs.STABLENORMAL_TURBO:
        from relight_backend.models.stablenormal import StableNormalTurbo

        return StableNormalTurbo
    raise KeyError(spec.key)


def run_model(
    spec: specs.ModelSpec, image: Image.Image, reporter: Reporter, stage: str, progress: float,
    extras: dict[str, FloatArray] | None = None,
) -> tuple[FloatArray, dict[str, Any]]:
    """Download if needed, then load, infer, unload. Returns the map and its stats."""

    def on_download(done: int, total: int) -> None:
        reporter.report(stage, progress, f"Downloading {spec.title}",
                        download_done_mb=done // _MB, download_total_mb=total // _MB)

    files = downloads.ensure(spec, on_download, reporter.check_cancel)
    reporter.check_cancel()
    reporter.report(stage, progress, f"Running {spec.title}")

    device = pick_device()
    model = model_class(spec)()
    with track_usage() as usage:
        try:
            output, infer_seconds = _load_and_infer(model, files, image, device)
        except torch.OutOfMemoryError:
            if device.type != "cuda":
                raise
            # Slower, but the user still gets maps; the stats record it.
            log.warning("%s ran out of VRAM; retrying on CPU", spec.title)
            reporter.report(stage, progress, f"{spec.title}: GPU out of memory, retrying on CPU")
            device = torch.device("cpu")
            output, infer_seconds = _load_and_infer(model, files, image, device)
    if extras is not None:
        extras.update(model.extras)
    stats = {
        "model": spec.key,
        "device": device.type,
        "load_seconds": round(usage.seconds - infer_seconds, 2),
        "infer_seconds": infer_seconds,
        "peak_vram_mb": usage.peak_vram_mb,
    }
    log.info("%s: %s", stage, stats)
    return output, stats


def _load_and_infer(
    model: Model, files: downloads.ModelFiles, image: Image.Image, device: torch.device
) -> tuple[FloatArray, float]:
    """Run one model and always unload it. Returns the map and the inference seconds."""
    try:
        model.load(files.weights, files.code, device, pick_dtype(device))
        loaded_at = time.perf_counter()
        output = model.infer(image)
        return output, round(time.perf_counter() - loaded_at, 2)
    finally:
        model.unload()


REACH_FILE = "reach.png"  # kept beside the depth; served to the app inside aux.png
SMOOTH_NORMALS_SIGMA = 0.006  # blur radius of the smooth normals, as a fraction of the width
BRIGHTNESS_SIGMA = 0.04  # ... and of the large-scale brightness


def smooth_normals(normals: FloatArray) -> FloatArray:
    """Blurred normals: the surface without fine bumps, compression blocks, or noise."""
    sigma = max(1.0, normals.shape[1] * SMOOTH_NORMALS_SIGMA)
    return normalize_vectors(np.asarray(cv2.GaussianBlur(normals, (0, 0), sigma), dtype=np.float32))


def large_scale_brightness(image: Image.Image) -> FloatArray:
    """Linear-light luminance of the photo, heavily blurred: how lit each region already is."""
    srgb = np.asarray(image, dtype=np.float32) / 255.0
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    luminance = (linear @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).astype(np.float32)
    sigma = max(1.0, image.width * BRIGHTNESS_SIGMA)
    return np.asarray(cv2.GaussianBlur(luminance, (0, 0), sigma), dtype=np.float32)


def _clear_maps(folder: Path) -> None:
    for path in folder.glob("*.png"):
        path.unlink()


def preprocess(
    store: SessionStore,
    session_id: str,
    source_name: str,
    options: PreprocessOptions,
    reporter: Reporter,
) -> SessionMeta:
    folder = store.folder(session_id)
    if folder is None:
        raise KeyError(f"No such session: {session_id}")
    normals_spec = specs.NORMALS[options.normals]

    reporter.report("prepare", 0.02, "Reading image")
    original = load_image(folder / ORIGINAL_FILE)
    working = resize_long_edge(original, options.working_long_edge)

    previous = store.load_meta(session_id)
    if previous is not None and previous.working_size != working.size:
        _clear_maps(folder)  # maps from a different working size cannot be reused
        previous = None
    stats: dict[str, Any] = dict(previous.stats) if previous else {}

    # Albedo proxy (v1): the image itself at working size; the shader linearizes it.
    albedo_path = folder / map_file("albedo_proxy", options.normals)
    if not albedo_path.exists():
        working.save(albedo_path)

    mask_path = folder / map_file("mask", options.normals)
    if not mask_path.exists():
        mask, stats["mask"] = run_model(specs.MASK, working, reporter, "mask", 0.05)
        save_gray8(mask, mask_path)

    reporter.check_cancel()
    depth_path = folder / map_file("depth", options.normals)
    reach_path = folder / REACH_FILE
    if depth_path.exists() and reach_path.exists():
        depth = load_gray16(depth_path)
    else:
        extras: dict[str, FloatArray] = {}
        depth, stats["depth"] = run_model(specs.DEPTH, working, reporter, "depth", 0.35, extras)
        save_gray16(depth, depth_path)
        save_gray8(extras.get("reach", np.ones_like(depth)), reach_path)

    reporter.check_cancel()
    normals_path = folder / map_file("normal", options.normals)
    if not normals_path.exists():
        if normals_spec is None:
            reporter.report("normals", 0.55, "Deriving normals from depth")
            started = time.perf_counter()
            normals = normals_from_depth(depth)
            normal_stats: dict[str, Any] = {
                "model": "depth-derived", "device": "cpu", "load_seconds": 0.0,
                "infer_seconds": round(time.perf_counter() - started, 2), "peak_vram_mb": None,
            }
        else:
            normals, normal_stats = run_model(normals_spec, working, reporter, "normals", 0.55)
        stats[f"normals_{options.normals}"] = normal_stats
        save_normals(normals, normals_path)

    smooth_path = folder / map_file("normal_smooth", options.normals)
    if not smooth_path.exists():
        save_normals(smooth_normals(load_normals(normals_path)), smooth_path)
    aux_path = folder / map_file("aux", options.normals)
    if not aux_path.exists():
        save_aux(load_gray8(reach_path), large_scale_brightness(working), aux_path,
                 thickness_code(load_gray8(mask_path)))

    meta = SessionMeta(
        id=session_id,
        source_name=source_name,
        original_size=original.size,
        working_size=working.size,
        normals_method=options.normals,
        mask_model=specs.MASK.key,
        stats=stats,
    )
    store.save_meta(meta)
    reporter.report("finish", 1.0, "Maps ready")
    return meta
