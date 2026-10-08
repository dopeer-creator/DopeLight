"""Export at the original image's full resolution.

The maps (normals, depth) are scaled up to the original size and shaded with
the same code the live preview is checked against (pipeline/shading.py), a
strip of rows at a time so memory stays bounded for large photos.

What gets written:

- relit        the relit image.
- light_layer  what the lights add, on black. Put it over the base image with
               the Add (Linear Dodge) blend mode to get the relit image.
- per_light    one such layer per light; together they add up to the light layer.

The base image is the original photo when the scene settings are at their
defaults (original light 1, ambient 0, exposure 0). Otherwise it is the photo
with those settings applied, and it is written too (`_base`), because the
layers only add up correctly on top of that.

Blend target:

- "normal": editors that add the stored (gamma-encoded) values, which is what
  Photoshop, Affinity Photo and Krita do in 8/16-bit documents. The layer is
  encode(relit) - encode(base).
- "linear": adding in linear light (GIMP's default, 32-bit documents, or
  Photoshop with "blend RGB colours using gamma 1.0"). The layer is
  encode(relit - base).

A layer can only add light. Where the relit image is darker than the base
(nowhere, unless a setting darkens it) the layer is black.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch

from relight_backend.pipeline.preprocess import Reporter
from relight_backend.pipeline.sessions import ORIGINAL_FILE, SessionStore, map_file
from relight_backend.pipeline.shading import (
    GlobalSettings,
    Light,
    Shaded,
    dilate_depth,
    linear_to_srgb,
    prepare_scene,
    shade_scene,
    srgb_to_linear,
)
from relight_backend.utils.device import pick_device, release_memory
from relight_backend.utils.image_io import (
    FloatArray,
    load_aux,
    load_gray16,
    load_image,
    load_normals,
    normalize_vectors,
    save_image,
)

log = logging.getLogger(__name__)

KINDS = ("relit", "light_layer", "per_light", "multiply")
PHOTOREAL_KINDS = ("relit", "light_layer", "multiply")
MULTIPLY_ONE = 0.5  # in a multiply layer this stored value means "times 1" (no change)
FORMATS = {"png": ".png", "jpeg": ".jpg", "tiff": ".tif"}
BLENDS = ("normal", "linear")
EXPORT_SHADOW_STEPS = 48  # the preview uses 24; an export can afford smoother shadows
STRIP_PIXELS = 1_000_000  # pixels shaded per strip


@dataclass(frozen=True)
class ExportOptions:
    kind: str = "relit"
    format: str = "png"
    bit_depth: int = 8  # 8 or 16; JPEG is always 8
    quality: int = 92  # JPEG only
    blend: str = "normal"
    alpha: bool = False  # layers: also write a transparent version

    def __post_init__(self) -> None:
        if self.kind not in KINDS or self.format not in FORMATS or self.blend not in BLENDS:
            raise ValueError(f"Unsupported export options: {self}")
        if self.bit_depth not in (8, 16):
            raise ValueError("bit_depth must be 8 or 16")

    @property
    def depth(self) -> int:
        return 8 if self.format == "jpeg" else self.bit_depth


def unique_path(path: Path) -> Path:
    """`path`, or `name (2).ext`, `name (3).ext`... if something is already there."""
    candidate, count = path, 1
    while candidate.exists():
        count += 1
        candidate = path.with_name(f"{path.stem} ({count}){path.suffix}")
    return candidate


def _slug(name: str) -> str:
    return re.sub(r"[^\w-]+", "_", name).strip("_") or "light"


def _scale_up(values: FloatArray, width: int, height: int) -> FloatArray:
    resized = cv2.resize(values, (width, height), interpolation=cv2.INTER_LINEAR)
    return np.asarray(resized, dtype=np.float32)


def _quantize(encoded: torch.Tensor, bit_depth: int) -> np.ndarray[Any, Any]:
    """Values 0..1 to uint8 or uint16."""
    top = 255.0 if bit_depth == 8 else 65535.0
    scaled = (encoded.clamp(0.0, 1.0) * top + 0.5).floor()
    return scaled.cpu().numpy().astype(np.uint8 if bit_depth == 8 else np.uint16)


def _with_alpha(layer: torch.Tensor) -> torch.Tensor:
    """Layer on black to straight-alpha RGBA: alpha is the brightest channel.

    Over black (or over any picture, with the Normal blend mode) this looks like
    the layer; it is the version for editors without an Add blend mode.
    """
    alpha = layer.amax(dim=-1, keepdim=True)
    colour = torch.where(alpha > 0, layer / alpha.clamp_min(1e-6), torch.zeros_like(layer))
    return torch.cat([colour, alpha], dim=-1)


def _layers(shaded: Shaded, blend: str) -> tuple[torch.Tensor, list[torch.Tensor]]:
    """(total layer, one layer per light), already encoded 0..1 for the blend target."""
    assert shaded.base is not None
    if blend == "normal":
        total = (linear_to_srgb(shaded.relit) - linear_to_srgb(shaded.base)).clamp_min(0.0)
    else:
        total = (shaded.relit - shaded.base).clamp_min(0.0)

    # Each light's share of the total, per channel, so the per-light layers add
    # up to the total exactly (the soft clip makes the raw sum too bright).
    raw_sum = torch.stack(shaded.raw_per_light).sum(dim=0) if shaded.raw_per_light else None
    parts = []
    for raw in shaded.raw_per_light:
        assert raw_sum is not None
        share = torch.where(raw_sum > 0, raw / raw_sum.clamp_min(1e-8), torch.zeros_like(raw))
        parts.append(total * share)

    if blend == "linear":
        return linear_to_srgb(total), [linear_to_srgb(part) for part in parts]
    return total, parts


def export(
    store: SessionStore,
    session_id: str,
    lights: list[Light],
    settings: GlobalSettings,
    options: ExportOptions,
    target: Path,
    reporter: Reporter,
) -> list[Path]:
    """Render and write the files. `target` names the main file; returns all files written."""
    folder, meta = store.folder(session_id), store.load_meta(session_id)
    if folder is None or meta is None:
        raise KeyError(f"No finished session: {session_id}")
    if options.kind == "multiply":
        raise ValueError("A multiply layer needs a photoreal render")

    reporter.report("export", 0.02, "Reading the full-size image")
    original = load_image(folder / ORIGINAL_FILE)
    width, height = original.size
    albedo = np.asarray(original, dtype=np.float32) / 255.0
    # Bilinear for both maps: a smoother filter would overshoot at depth edges.
    normals = normalize_vectors(_scale_up(
        load_normals(folder / map_file("normal", meta.normals_method)), width, height
    ))
    working_depth = load_gray16(folder / map_file("depth", meta.normals_method))
    depth = _scale_up(working_depth, width, height)
    # The maps derived from depth are made at the working size, as in the live
    # preview, and scaled up with it: same look, and far cheaper than at full size.
    working = torch.from_numpy(working_depth)
    tops = _scale_up(dilate_depth(working).numpy(), width, height)

    smooth = normalize_vectors(_scale_up(
        load_normals(folder / map_file("normal_smooth", meta.normals_method)), width, height
    ))
    working_reach, working_brightness, working_rim = load_aux(
        folder / map_file("aux", meta.normals_method)
    )
    reach = _scale_up(working_reach, width, height)
    brightness = _scale_up(working_brightness, width, height)
    rim = _scale_up(working_rim, width, height)

    active = [light for light in lights if light.enabled]
    suffix = FORMATS[options.format]
    target = target.with_suffix(suffix)
    # Only these three change the base image; the others only change what lights add.
    plain = GlobalSettings()
    plain_settings = (
        settings.keep_original_light == plain.keep_original_light
        and settings.ambient == plain.ambient
        and settings.exposure == plain.exposure
    )

    # name -> (path, channels). Arrays are filled strip by strip.
    planned: dict[str, tuple[Path, int]] = {}
    if options.kind == "relit":
        planned["relit"] = (target, 3)
    else:
        if options.kind == "light_layer":
            planned["layer"] = (target, 3)
        else:
            for index, light in enumerate(active):
                name = f"{target.stem}_{index + 1}_{_slug(light.name)}{suffix}"
                planned[f"light{index}"] = (unique_path(target.with_name(name)), 3)
        if options.alpha:
            # Transparency needs PNG or TIFF.
            alpha_suffix = ".png" if options.format == "jpeg" else suffix
            for key, (path, _channels) in list(planned.items()):
                alpha_path = path.with_name(f"{path.stem}_alpha{alpha_suffix}")
                planned[f"{key}_alpha"] = (unique_path(alpha_path), 4)
        if not plain_settings:
            base_path = target.with_name(f"{target.stem}_base{suffix}")
            planned["base"] = (unique_path(base_path), 3)

    dtype = np.uint8 if options.depth == 8 else np.uint16
    arrays = {key: np.zeros((height, width, channels), dtype=dtype)
              for key, (_path, channels) in planned.items()}

    def render(device: torch.device) -> None:
        scene = prepare_scene(albedo, normals, depth, device, tops, rim, smooth, reach,
                              brightness)
        strip = max(1, STRIP_PIXELS // width)
        for start in range(0, height, strip):
            reporter.check_cancel()
            end = min(height, start + strip)
            reporter.report("export", 0.05 + 0.85 * start / height,
                            f"Rendering rows {start + 1} to {end} of {height}")
            shaded = shade_scene(scene, lights, settings, shadow_steps=EXPORT_SHADOW_STEPS,
                                 rows=(start, end))
            results: dict[str, torch.Tensor] = {}
            if "relit" in planned:
                results["relit"] = linear_to_srgb(shaded.relit)
            else:
                total, parts = _layers(shaded, options.blend)
                results["layer"] = total
                results.update({f"light{index}": part for index, part in enumerate(parts)})
                assert shaded.base is not None
                results["base"] = linear_to_srgb(shaded.base)
            for key in planned:
                source = key.removesuffix("_alpha")
                value = _with_alpha(results[source]) if key.endswith("_alpha") else results[key]
                arrays[key][start:end] = _quantize(value, options.depth)

    device = pick_device()
    try:
        render(device)
    except torch.OutOfMemoryError:
        if device.type != "cuda":
            raise
        log.warning("export ran out of VRAM; retrying on CPU")
        reporter.report("export", 0.05, "GPU out of memory, rendering on CPU")
        release_memory()
        render(torch.device("cpu"))
    finally:
        release_memory()

    reporter.check_cancel()
    reporter.report("export", 0.92, "Writing files")
    written = []
    for key, (path, _channels) in planned.items():
        file_format = "png" if path.suffix == ".png" else options.format
        save_image(arrays[key], path, file_format, options.quality)
        written.append(path)
    log.info("exported %s", [str(path) for path in written])
    reporter.report("finish", 1.0, f"Saved {len(written)} file{'s' if len(written) != 1 else ''}")
    return written


def export_photoreal(
    store: SessionStore,
    session_id: str,
    render_id: str,
    options: ExportOptions,
    target: Path,
    reporter: Reporter,
) -> list[Path]:
    """Write files from a photoreal render (pipeline/photoreal.py) at full size.

    - relit        the original times the render's lighting ratio.
    - light_layer  what got brighter, on black, for the Add blend mode. Shadows the
                   render added cannot be in it: a layer that adds cannot darken.
    - multiply     the lighting ratio itself, for the Multiply blend mode in a
                   linear-light (32-bit) document. Stored value 0.5 means "no
                   change", 1.0 means twice as bright; ratios above 2 are clipped.
                   Unlike the light layer it carries the new shadows too.
    """
    from relight_backend.pipeline import photoreal

    folder = store.folder(session_id)
    renders = photoreal.render_folder(store, session_id, render_id)
    if folder is None or renders is None:
        raise KeyError(f"No such render: {render_id}")
    if options.kind not in PHOTOREAL_KINDS:
        raise ValueError(f"A photoreal render cannot be exported as {options.kind!r}")

    reporter.report("export", 0.05, "Reading the full-size image")
    original = np.asarray(load_image(folder / ORIGINAL_FILE), dtype=np.float32) / 255.0
    ratio = np.load(renders / photoreal.RATIO_FILE).astype(np.float32)
    height, width = original.shape[:2]

    reporter.check_cancel()
    reporter.report("export", 0.3, "Applying the light")
    if options.kind == "multiply":
        full_ratio = np.asarray(cv2.resize(ratio, (width, height), interpolation=cv2.INTER_LINEAR))
        encoded = torch.from_numpy(np.clip(full_ratio * MULTIPLY_ONE, 0.0, 1.0))
    else:
        relit = torch.from_numpy(photoreal.apply_ratio(original, ratio))
        base = srgb_to_linear(torch.from_numpy(original))
        if options.kind == "relit":
            encoded = linear_to_srgb(relit)
        elif options.blend == "normal":
            encoded = (linear_to_srgb(relit) - linear_to_srgb(base)).clamp_min(0.0)
        else:
            encoded = linear_to_srgb((relit - base).clamp_min(0.0))

    suffix = FORMATS[options.format]
    target = target.with_suffix(suffix)
    written = [target]
    reporter.check_cancel()
    reporter.report("export", 0.8, "Writing files")
    save_image(_quantize(encoded, options.depth), target, options.format, options.quality)
    if options.alpha and options.kind == "light_layer":
        alpha_suffix = ".png" if options.format == "jpeg" else suffix
        alpha_path = unique_path(target.with_name(f"{target.stem}_alpha{alpha_suffix}"))
        save_image(_quantize(_with_alpha(encoded), options.depth), alpha_path,
                   "png" if alpha_suffix == ".png" else options.format)
        written.append(alpha_path)
    reporter.report("finish", 1.0, f"Saved {len(written)} file{'s' if len(written) != 1 else ''}")
    return written
