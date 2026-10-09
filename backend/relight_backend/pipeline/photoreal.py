"""Photoreal pass: redraw the lighting with IC-Light, guided by the user's lights.

1. Shade the scene with the preview's own math (pipeline/shading.py) at the
   diffusion size. That picture is the lighting hint: it ties the light gizmos
   to the result.
2. IC-Light relights the photo, starting from the hint.
3. Detail-preserving transfer: only the *lighting ratio* relit / original is
   taken from the diffusion result, smoothed (edges kept, guided by the
   original), scaled up, and multiplied into the full-size original. The
   original's texture and detail stay; faces do not turn into someone else.

Each render is kept in <session>/renders/<id>/: the ratio (for exports at any
bit depth) and a preview picture for the app.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from PIL import Image

from relight_backend.models import specs
from relight_backend.models.iclight import IcLight, RelightParams, round64
from relight_backend.pipeline.preprocess import Reporter
from relight_backend.pipeline.sessions import ORIGINAL_FILE, SessionStore, map_file
from relight_backend.pipeline.shading import (
    GlobalSettings,
    Light,
    Scene,
    prepare_scene,
    shade_scene,
    soft_clip,
    to_srgb8,
)
from relight_backend.utils import downloads
from relight_backend.utils.device import pick_device, pick_dtype, release_memory
from relight_backend.utils.image_io import (
    FloatArray,
    load_aux,
    load_gray8,
    load_gray8_or_zeros,
    load_gray16,
    load_image,
    load_normals,
    normalize_vectors,
)
from relight_backend.utils.vram import track_usage

log = logging.getLogger(__name__)

_MB = 1024 * 1024
RATIO_FILE = "ratio.npy"
PREVIEW_FILE = "preview.jpg"
PREVIEW_LONG_EDGE = 1536
RATIO_MIN, RATIO_MAX = 0.05, 12.0  # sane bounds for relit / original
RATIO_EPSILON = 0.03  # added to both sides of the ratio: tames it in near-black areas,
# and is what lets those areas gain light (see apply_ratio)
GUIDED_RADIUS = 0.012  # edge-keeping smoothing radius, as a fraction of the width
GUIDED_EPSILON = 0.01
COLOUR_LIMIT = 1.5  # a channel may change at most this much more (or less) than brightness
COLOUR_SIGMA = 0.04  # blur of the colour change, as a fraction of the width
SUBJECT_FEATHER = 0.006  # softening of the subject mask's edge, as a fraction of the width
# The largest ratio that means anything: it takes a black pixel to full white.
RATIO_FULL = (1.0 + RATIO_EPSILON) / RATIO_EPSILON
BRIGHTNESS_LEASH = 2.5  # how far the model's brightness may depart from the preview's
MODEL_COLOUR_LIMIT = 3.0  # bound on the model's own colour, where it is used at all
# The user's lights own the colour where they supply this share of the brightness or more.
LIGHT_SHARE_LOW = 0.1
LIGHT_SHARE_FULL = 0.45
MIN_SUBJECT_SHARE = 0.02  # below this share of the picture, there is no subject to speak of
# On out-of-memory the render is retried smaller, then with the slowest, leanest loading.
RETRY_SCALES = (1.0, 0.8, 0.64)
CPU_LONG_EDGE = 512  # diffusion size cap when there is no GPU


@dataclass(frozen=True)
class RenderOptions:
    prompt: str = "beautiful lighting, natural"
    steps: int = 25
    adherence: float = 0.5  # 0..1: how closely the result follows the light placement
    seed: int = 12345
    long_edge: int = 768  # diffusion size before the high-resolution pass
    highres: bool = True

    def params(self) -> RelightParams:
        # More adherence = less freedom to move away from the hint.
        denoise = 0.95 - 0.45 * min(max(self.adherence, 0.0), 1.0)
        return RelightParams(prompt=self.prompt, steps=self.steps, denoise=denoise,
                             seed=self.seed, highres=self.highres)


def _linear(srgb: FloatArray) -> FloatArray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4).astype(
        np.float32
    )


def _srgb(linear: FloatArray) -> FloatArray:
    value = np.clip(linear, 0.0, 1.0)
    return np.where(value <= 0.0031308, value * 12.92,
                    1.055 * value ** (1.0 / 2.4) - 0.055).astype(np.float32)


def _resize(values: FloatArray, size: tuple[int, int]) -> FloatArray:
    return np.asarray(cv2.resize(values, size, interpolation=cv2.INTER_LINEAR), dtype=np.float32)


def guided_filter(guide: FloatArray, values: FloatArray, radius: int, epsilon: float) -> FloatArray:
    """Smooth `values` (H, W, C) while keeping the edges of `guide` (H, W)."""
    size = (2 * radius + 1, 2 * radius + 1)

    def box(image: Any) -> FloatArray:
        return np.asarray(cv2.boxFilter(image, -1, size), dtype=np.float32)

    mean_guide = box(guide)
    variance = box(guide * guide) - mean_guide * mean_guide
    result = np.empty_like(values)
    for channel in range(values.shape[2]):
        target = values[..., channel]
        mean_target = box(target)
        slope = (box(guide * target) - mean_guide * mean_target) / (variance + epsilon)
        offset = mean_target - slope * mean_guide
        result[..., channel] = box(slope) * guide + box(offset)
    return result


_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _raw_ratio(original_linear: FloatArray, relit_linear: FloatArray) -> FloatArray:
    # The same small amount on both sides: an unchanged pixel gives exactly 1, and
    # near-black pixels cannot produce huge ratios.
    return np.asarray(
        (relit_linear + RATIO_EPSILON) / (original_linear + RATIO_EPSILON), dtype=np.float32
    )


def lighting_ratio(
    original: FloatArray, relit: FloatArray,
    hint: FloatArray | None = None, subject: FloatArray | None = None,
    base_level: float = 1.0,
) -> FloatArray:
    """The change in light, as a per-channel ratio. Inputs: sRGB floats, same size.

    The diffusion model shades realistically but also repaints: it recolours
    things and invents backgrounds. So brightness and colour are taken from
    different places:

    - **Brightness** (how light and shadow fall) comes from the model.
    - **Colour** comes from `hint`, the preview's own shading of the user's
      lights, in full, wherever those lights land: a saturated blue light gives a
      saturated blue result, and the model cannot turn a blue jacket teal there.
      Where the user's lights do not reach but the model adds light anyway (bounce,
      spill), there is no light colour to use, so the model's own colour is kept;
      otherwise that light would come out grey. `base_level` is how bright the
      unlit photo is in the hint (original light + ambient, times exposure); it
      tells the two cases apart.
    - Off the subject (`subject` mask), the whole ratio comes from the hint. The
      model is a foreground relighter and its backgrounds are inventions.

    Every picture is smoothed first (keeping the original's edges) and divided
    afterwards. Dividing pixel by pixel and smoothing the result looks the same
    in bright areas but falls apart in dark ones, where noise in a near-zero
    original turns into blotches. Smoothing also removes the dotted edges of the
    preview's shadows.

    Without a hint there is no record of the lights, and a broad, limited part
    of the model's own colour change is kept instead.
    """
    original_linear = _linear(original)
    guide = np.asarray(original_linear @ _LUMA, dtype=np.float32)
    width = original.shape[1]
    radius = max(1, round(width * GUIDED_RADIUS))

    def smooth(picture: FloatArray) -> FloatArray:
        return np.maximum(guided_filter(guide, picture, radius, GUIDED_EPSILON), 0.0)

    def brightness_of(picture: FloatArray) -> FloatArray:
        return np.asarray((picture @ _LUMA)[..., None], dtype=np.float32)

    base = smooth(original_linear)
    model = smooth(_linear(relit))
    brightness = _raw_ratio(brightness_of(base), brightness_of(model))

    if hint is None:
        tint = _raw_ratio(base, model) / np.maximum(brightness, 1e-3)
        tint = np.clip(tint, 1.0 / COLOUR_LIMIT, COLOUR_LIMIT).astype(np.float32)
        broad_tint = cv2.GaussianBlur(tint, (0, 0), max(1.0, width * COLOUR_SIGMA))
        ratio = np.asarray(brightness * broad_tint, dtype=np.float32)
        return np.asarray(np.clip(ratio, RATIO_MIN, RATIO_MAX), dtype=np.float32)

    lights = smooth(_linear(hint))
    preview = _raw_ratio(base, lights)  # the preview's light
    preview_brightness = _raw_ratio(brightness_of(base), brightness_of(lights))
    light_colour = preview / np.maximum(preview_brightness, 1e-3)
    # The leash: the model may refine how bright each spot is, within a factor of
    # what the preview's physics gives. Past that it is repainting (a black cloth
    # redrawn as a pale one), not lighting.
    freedom = np.clip(brightness / np.maximum(preview_brightness, 1e-3),
                      1.0 / BRIGHTNESS_LEASH, BRIGHTNESS_LEASH)
    brightness = np.asarray(preview_brightness * freedom, dtype=np.float32)
    model_colour = np.clip(_raw_ratio(base, model) / np.maximum(brightness, 1e-3),
                           1.0 / MODEL_COLOUR_LIMIT, MODEL_COLOUR_LIMIT)
    # Share of the hint's brightness that comes from the user's lights, 0..1.
    unlit = base_level * brightness_of(base)
    share = np.clip(1.0 - unlit / (brightness_of(lights) + RATIO_EPSILON), 0.0, 1.0)
    t = np.clip((share - LIGHT_SHARE_LOW) / (LIGHT_SHARE_FULL - LIGHT_SHARE_LOW), 0.0, 1.0)
    weight = t * t * (3.0 - 2.0 * t)
    colour = weight * light_colour + (1.0 - weight) * model_colour
    ratio = np.asarray(brightness * colour, dtype=np.float32)

    if subject is not None and float(subject.mean()) >= MIN_SUBJECT_SHARE:
        soft = cv2.GaussianBlur(subject, (0, 0), max(1.0, width * SUBJECT_FEATHER))
        ratio = soft[..., None] * ratio + (1.0 - soft[..., None]) * preview
    return np.asarray(np.clip(ratio, RATIO_MIN, RATIO_MAX), dtype=np.float32)


def smoothed_preview_ratio(original: FloatArray, hint: FloatArray) -> FloatArray:
    """The preview's light as lighting_ratio sees it: both pictures smoothed, then divided."""
    original_linear = _linear(original)
    guide = np.asarray(original_linear @ _LUMA, dtype=np.float32)
    radius = max(1, round(original.shape[1] * GUIDED_RADIUS))
    base = np.maximum(guided_filter(guide, original_linear, radius, GUIDED_EPSILON), 0.0)
    lights = np.maximum(guided_filter(guide, _linear(hint), radius, GUIDED_EPSILON), 0.0)
    return _raw_ratio(base, lights)


def model_correction(ratio: FloatArray, preview_low: FloatArray) -> FloatArray:
    """What the model changed, relative to the preview's own light. 1 = it agrees.

    Both arguments are ratios to the original at the diffusion size: the model's
    light (`lighting_ratio`) and the preview's (`smoothed_preview_ratio`). The
    result is broad and bounded: brightness within the leash, and the model's
    colour only where the user's lights do not decide it.
    """
    limit = BRIGHTNESS_LEASH * MODEL_COLOUR_LIMIT
    correction = ratio / np.maximum(preview_low, 1e-3)
    return np.asarray(np.clip(correction, 1.0 / limit, limit), dtype=np.float32)


def compose_ratio(
    correction: FloatArray, original: FloatArray, shading: FloatArray, rim: FloatArray
) -> FloatArray:
    """The final ratio, at the working size: the preview's picture, corrected by the model.

    `original`, `shading`, and `rim` are linear light at the working size:
    the photo, the preview's shading of it without rim light, and the rim light
    by itself, the last two before the highlight roll-off. The result is

        roll-off(shading * correction + rim)

    so every edge of light is the preview's, exact per pixel: along a muscle, a
    fold, a shadow. The model only scales it, broadly. (Before, the model's
    light was measured small and smoothed, and the result was soft.)

    - The correction multiplies the shading itself, not a ratio with the
      epsilon in it. A black cloth the lights do not reach stays black; with the
      epsilon a "2.5 times brighter" from the model turned it grey.
    - The rim is added untouched. The model does not draw rims, so measured
      against it a rim only ever came out dimmer, and its colour washed out.
    - Nothing is capped per channel short of full white, so a saturated light on
      dark hair keeps its colour.
    """
    height, width = original.shape[:2]
    lit = soft_clip(torch.from_numpy(shading * _resize(correction, (width, height)) + rim))
    ratio = (lit.clamp(0.0, 1.0).numpy() + RATIO_EPSILON) / (original + RATIO_EPSILON)
    return np.asarray(np.clip(ratio, RATIO_MIN, RATIO_FULL), dtype=np.float32)


def apply_ratio(original: FloatArray, ratio: FloatArray) -> FloatArray:
    """Full-size relit image (linear light, 0..1) from the original (sRGB floats) and a ratio.

    The exact inverse of how the ratio was measured, (relit + e) / (original + e):
    bright areas are scaled, keeping their texture, while near-black areas gain
    light additively. A plain multiplication could never light a black background.
    """
    height, width = original.shape[:2]
    scaled = (_linear(original) + RATIO_EPSILON) * _resize(ratio, (width, height))
    return np.asarray(np.clip(scaled - RATIO_EPSILON, 0.0, 1.0), dtype=np.float32)


def load_scene(folder: Path, normals_method: str, size: tuple[int, int],
               ) -> tuple[Image.Image, Scene]:
    """(the photo, its maps ready for shading) at the given size."""
    photo = Image.open(folder / map_file("albedo_proxy", normals_method)).convert("RGB")
    photo = photo.resize(size, Image.Resampling.LANCZOS)
    reach, brightness, rim = load_aux(folder / map_file("aux", normals_method))
    scene = prepare_scene(
        np.asarray(photo, dtype=np.float32) / 255.0,
        normalize_vectors(_resize(load_normals(folder / map_file("normal", normals_method)), size)),
        _resize(load_gray16(folder / map_file("depth", normals_method)), size),
        normal_smooth=normalize_vectors(
            _resize(load_normals(folder / map_file("normal_smooth", normals_method)), size)
        ),
        reach=_resize(reach, size),
        brightness=_resize(brightness, size),
        rim=_resize(rim, size),
        # A session from before the thickness map has none: everything is solid then.
        thickness=_resize(
            load_gray8_or_zeros(folder / map_file("thickness", normals_method), reach), size
        ),
    )
    return photo, scene


def shade_parts(scene: Scene, lights: list[Light], settings: GlobalSettings,
                ) -> tuple[FloatArray, FloatArray]:
    """(the preview's shading without rim light, the rim light alone), linear light.

    Both are taken before the highlight roll-off: their sum, rolled off, is the
    preview's picture.
    """
    whole = shade_scene(scene, lights, settings).unclipped
    plain = shade_scene(replace(scene, rim=torch.zeros_like(scene.rim)), lights,
                        settings).unclipped
    assert whole is not None and plain is not None
    return (np.asarray(plain.cpu().numpy(), dtype=np.float32),
            np.asarray((whole - plain).clamp_min(0.0).cpu().numpy(), dtype=np.float32))


def make_hint(folder: Path, normals_method: str, size: tuple[int, int], lights: list[Light],
              settings: GlobalSettings) -> tuple[Image.Image, Image.Image]:
    """(the photo, the lighting hint) at the diffusion size."""
    photo, scene = load_scene(folder, normals_method, size)
    shaded = shade_scene(scene, lights, settings)
    return photo, Image.fromarray(to_srgb8(shaded.relit), mode="RGB")


def transfer(
    folder: Path, normals_method: str, working_size: tuple[int, int], relit: Image.Image,
    lights: list[Light], settings: GlobalSettings,
) -> FloatArray:
    """The lighting ratio at the working size, from the model's picture and the preview's."""
    original = load_image(folder / ORIGINAL_FILE)
    small = np.asarray(original.resize(relit.size, Image.Resampling.LANCZOS),
                       dtype=np.float32) / 255.0
    subject = _resize(load_gray8(folder / map_file("mask", normals_method)), relit.size)
    # The model is compared with the preview without its rim light: it draws no
    # rims, and beside one it would only seem to have darkened the edge.
    _photo, small_scene = load_scene(folder, normals_method, relit.size)
    plain_small = _srgb(soft_clip(torch.from_numpy(
        shade_parts(small_scene, lights, settings)[0])).numpy())
    base_level = (settings.keep_original_light + settings.ambient) * 2.0**settings.exposure
    ratio = lighting_ratio(small, np.asarray(relit, dtype=np.float32) / 255.0, plain_small,
                           subject, base_level)
    correction = model_correction(ratio, smoothed_preview_ratio(small, plain_small))

    photo, scene = load_scene(folder, normals_method, working_size)
    shading, rim = shade_parts(scene, lights, settings)
    return compose_ratio(correction, _linear(np.asarray(photo, dtype=np.float32) / 255.0),
                         shading, rim)


def _step_reporter(reporter: Reporter, total: int) -> Callable[[], None]:
    """A callback for each denoising step: reports progress, and raises if cancelled."""
    done = 0

    def on_step() -> None:
        nonlocal done
        done += 1
        reporter.check_cancel()
        reporter.report("render", 0.1 + 0.8 * min(done / total, 1.0),
                        f"Relighting, step {min(done, total)} of {total}")

    return on_step


def render_folder(store: SessionStore, session_id: str, render_id: str) -> Path | None:
    folder = store.folder(session_id)
    if folder is None or not render_id.isalnum():
        return None
    path = folder / "renders" / render_id
    return path if (path / RATIO_FILE).exists() else None


def render(
    store: SessionStore, session_id: str, lights: list[Light], settings: GlobalSettings,
    options: RenderOptions, reporter: Reporter,
) -> dict[str, Any]:
    folder, meta = store.folder(session_id), store.load_meta(session_id)
    if folder is None or meta is None:
        raise KeyError(f"No finished session: {session_id}")

    files: dict[str, Path] = {}
    for spec in specs.PHOTOREAL:
        def on_download(done: int, total: int, spec: specs.ModelSpec = spec) -> None:
            reporter.report("download", 0.0, f"Downloading {spec.title}",
                            download_done_mb=done // _MB, download_total_mb=total // _MB)

        files[spec.key] = downloads.ensure(spec, on_download, reporter.check_cancel).weights

    working_width, working_height = meta.working_size
    device = pick_device()
    params = options.params()
    model = IcLight()
    started = time.perf_counter()
    relit: Image.Image | None = None
    note = ""
    long_edge = options.long_edge
    if device.type == "cpu" and long_edge > CPU_LONG_EDGE:
        # Without a GPU the full size would take the better part of an hour.
        long_edge = CPU_LONG_EDGE
        note = "No NVIDIA graphics card: rendered at a smaller size to keep the wait bearable."

    with track_usage() as usage:
        try:
            for attempt, scale in enumerate(RETRY_SCALES):
                factor = long_edge * scale / max(working_width, working_height)
                size = (round64(working_width * factor), round64(working_height * factor))
                reporter.check_cancel()
                reporter.report("render", 0.03, f"Loading the model ({device.type})")
                try:
                    model.load(files[specs.SD15_REALISTIC.key], files[specs.IC_LIGHT_FC.key],
                               device, pick_dtype(device), low_memory=attempt > 0)
                    photo, hint = make_hint(folder, meta.normals_method, size, lights, settings)
                    on_step = _step_reporter(reporter, model.total_steps(params))
                    relit = model.relight(photo, hint, params, on_step)
                    break
                except torch.OutOfMemoryError:
                    model.unload()
                    if device.type != "cuda" or attempt == len(RETRY_SCALES) - 1:
                        raise
                    note = "The graphics card ran out of memory; rendered at a smaller size."
                    log.warning("photoreal render out of VRAM at %s; retrying smaller", size)
                    reporter.report("render", 0.03, "Out of GPU memory, retrying smaller")
        finally:
            model.unload()
            release_memory()
    assert relit is not None

    reporter.report("transfer", 0.92, "Applying the new light to the full-size photo")
    ratio = transfer(folder, meta.normals_method, (working_width, working_height), relit,
                     lights, settings)
    original = load_image(folder / ORIGINAL_FILE)

    render_id = uuid.uuid4().hex[:12]
    out = folder / "renders" / render_id
    out.mkdir(parents=True)
    np.save(out / RATIO_FILE, ratio.astype(np.float16))
    preview = original.copy()
    preview.thumbnail((PREVIEW_LONG_EDGE, PREVIEW_LONG_EDGE), Image.Resampling.LANCZOS)
    shown = _srgb(apply_ratio(np.asarray(preview, dtype=np.float32) / 255.0, ratio))
    Image.fromarray((shown * 255.0 + 0.5).astype(np.uint8), mode="RGB").save(
        out / PREVIEW_FILE, quality=93
    )
    relit.save(out / "diffusion.jpg", quality=93)  # the raw model output, for inspection
    hint.save(out / "hint.jpg", quality=93)

    result = {
        "render_id": render_id,
        "diffusion_size": list(relit.size),
        "device": device.type,
        "seconds": round(time.perf_counter() - started, 1),
        "peak_vram_mb": usage.peak_vram_mb,
        "note": note,
        "options": asdict(options),
    }
    (out / "meta.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log.info("photoreal render %s", result)
    reporter.report("finish", 1.0, "Render ready")
    return result
