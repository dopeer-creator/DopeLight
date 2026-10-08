"""The Python reference shading: behaviour, and agreement with the app's constants."""

import re
from pathlib import Path

import numpy as np
import pytest
import torch

from relight_backend.constants import DEPTH_SCALE
from relight_backend.pipeline import shading
from relight_backend.pipeline.shading import GlobalSettings, Light, shade, soft_clip, to_srgb8

LIGHTING_TS = Path(__file__).resolve().parents[2] / "app" / "src" / "shared" / "lighting.ts"

H, W = 40, 60
FACING = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (H, W, 1))  # flat, toward viewer
FLAT = np.full((H, W), 0.5, dtype=np.float32)
GREY = np.full((H, W, 3), 0.5, dtype=np.float32)
NO_BASE = GlobalSettings(keep_original_light=0.0)


def lit(light: Light, normals: np.ndarray = FACING, depth: np.ndarray = FLAT,
        settings: GlobalSettings = NO_BASE) -> torch.Tensor:
    return shade(GREY, normals, depth, [light], settings, jitter=0.0).relit


def test_constants_match_the_app() -> None:
    """lighting.ts feeds the shader; shading.py must use the same numbers."""
    text = LIGHTING_TS.read_text(encoding="utf-8")
    block = re.search(r"export const SHADING = \{(.*?)\} as const", text, re.S)
    assert block, "SHADING block not found in lighting.ts"
    app = {name: float(value) for name, value in re.findall(r"(\w+):\s*([\d.]+)", block.group(1))}
    assert app == {
        "depthScale": DEPTH_SCALE,
        "wrapK": shading.WRAP_K,
        "specFade": shading.SPEC_FADE,
        "shadowBias": shading.SHADOW_BIAS,
        "shadowSoftMin": shading.SHADOW_SOFT_MIN,
        "shadowSoftMax": shading.SHADOW_SOFT_MAX,
        "shadowReach": shading.SHADOW_REACH,
        "shadowThickness": shading.SHADOW_THICKNESS,
        "embedFade": shading.EMBED_FADE,
        "shellDilate": shading.SHELL_DILATE,
        "rimStrength": shading.RIM_STRENGTH,
        "rimEdgeScale": shading.RIM_EDGE_SCALE,
        "rimWidth": shading.RIM_WIDTH,
        "rimWhite": shading.RIM_WHITE,
        "softClipStart": shading.SOFT_CLIP_START,
        "targetHeight": shading.TARGET_HEIGHT,
        "defaultShadowSteps": shading.DEFAULT_SHADOW_STEPS,
    }
    max_lights = re.search(r"export const MAX_LIGHTS = (\d+)", text)
    assert max_lights and int(max_lights.group(1)) == shading.MAX_LIGHTS


def test_no_lights_returns_the_image_unchanged() -> None:
    rng = np.random.default_rng(0)
    image8 = rng.integers(0, 230, size=(H, W, 3), dtype=np.uint8)  # below the soft-clip start
    result = shade(image8.astype(np.float32) / 255.0, FACING, FLAT, [], GlobalSettings())
    assert np.array_equal(to_srgb8(result.relit), image8)
    assert float(result.light_layer.max()) == 0.0


def test_light_is_brightest_under_itself_and_fades_with_distance() -> None:
    result = lit(Light(x=0.25, y=0.5, z=0.6, specular=0.0))
    row = result[H // 2, :, 0]
    assert int(row.argmax()) == pytest.approx(0.25 * W, abs=1)
    assert row[int(0.25 * W)] > row[int(0.6 * W)] > row[W - 1] > 0


def test_surface_facing_away_gets_no_light_unless_diffusion_wraps_it() -> None:
    away = np.tile(np.array([-1.0, 0.0, 0.0], dtype=np.float32), (H, W, 1))  # faces left
    right_side = Light(x=1.2, y=0.5, z=0.25, specular=0.0, diffusion=0.0)
    assert float(lit(right_side, normals=away).max()) == 0.0
    wrapped = Light(x=1.2, y=0.5, z=0.25, specular=0.0, diffusion=1.0)
    assert float(lit(wrapped, normals=away)[H // 2, W - 2, 0]) > 0.0


def test_directional_light_is_even_across_a_flat_surface() -> None:
    sun = Light(type="directional", x=0.5, y=0.5, z=2.0, target_x=0.5, target_y=0.5, specular=0.0)
    result = lit(sun)
    assert float(result.max() - result.min()) < 1e-5 and float(result.min()) > 0.1


def test_spot_light_is_dark_outside_its_cone() -> None:
    spot = Light(type="spot", x=0.2, y=0.5, z=0.8, target_x=0.2, target_y=0.5,
                 cone_angle=30.0, cone_softness=0.2, specular=0.0)
    result = lit(spot)
    assert float(result[H // 2, int(0.2 * W), 0]) > 0.05
    assert float(result[H // 2, W - 1, 0]) == 0.0


def test_specular_adds_a_highlight() -> None:
    matte = lit(Light(x=0.5, y=0.5, z=0.6, specular=0.0))
    glossy = lit(Light(x=0.5, y=0.5, z=0.6, specular=1.0, shininess=20.0))
    centre = (H // 2, W // 2, 0)
    assert float(glossy[centre]) > float(matte[centre])


def test_shadow_falls_behind_a_block_only() -> None:
    depth = np.full((H, W), 0.1, dtype=np.float32)
    depth[:, 25:30] = 1.0  # a wall across the picture
    lamp = dict(x=0.05, y=0.5, z=0.2, specular=0.0, diffusion=0.0)
    without = lit(Light(**lamp), depth=depth)  # type: ignore[arg-type]
    shadowed = lit(Light(**lamp, cast_shadows=True, shadow_strength=1.0), depth=depth)  # type: ignore[arg-type]

    behind, in_front = (H // 2, 40, 0), (H // 2, 10, 0)
    assert float(without[behind]) > 0.0
    assert float(shadowed[behind]) == pytest.approx(0.0, abs=1e-6)
    assert float(shadowed[in_front]) == pytest.approx(float(without[in_front]), rel=1e-5)


def test_light_behind_a_shape_still_reaches_the_floor_around_it() -> None:
    """A light tucked behind a raised block is in open space: it lights the floor
    beside the block, while the block's own front stays dark."""
    depth = np.full((H, W), 0.1, dtype=np.float32)  # floor at z = 0.04
    depth[10:30, 20:40] = 1.0  # a block in the middle, front face at z = 0.4
    back = Light(x=0.5, y=0.5, z=0.08, specular=0.0, diffusion=0.0,
                 cast_shadows=True, shadow_strength=1.0)
    assert shading.light_embed(back, torch.from_numpy(depth), H / W) == pytest.approx(0.32)

    result = lit(back, depth=depth)
    floor_beside, block_front = (H // 2, 10, 0), (H // 2, W // 2, 0)
    assert float(result[floor_beside]) > 0.01
    assert float(result[block_front]) == 0.0  # faces the viewer, away from its outline


def test_light_behind_a_shape_gives_it_a_glowing_outline() -> None:
    depth = np.full((H, W), 0.1, dtype=np.float32)
    depth[10:30, 20:40] = 1.0
    back = Light(x=0.5, y=0.5, z=0.08, specular=0.0, diffusion=0.0)
    result = lit(back, depth=depth)
    edge, centre, floor_far = (H // 2, 20, 0), (H // 2, W // 2, 0), (2, 2, 0)
    assert float(result[edge]) > 0.2  # the block's outline glows
    assert float(result[centre]) == 0.0  # its middle does not
    outline = shading.outline_map(torch.from_numpy(depth))
    assert float(outline[edge[0], edge[1]]) == 1.0 and float(outline[centre[0], centre[1]]) == 0.0
    assert float(outline[floor_far[0], floor_far[1]]) == 0.0  # the low side of an edge has none


def test_light_in_front_gives_no_rim() -> None:
    depth = np.full((H, W), 0.1, dtype=np.float32)
    depth[10:30, 20:40] = 1.0
    front = Light(x=0.5, y=0.5, z=1.5, specular=0.0)
    flat_scene = lit(front, depth=np.full((H, W), 1.0, dtype=np.float32))
    with_block = lit(front, depth=depth)
    # On top of the block the light is in front: same value as a flat surface at that height.
    on_block = (H // 2, 21, 0)
    assert float(with_block[on_block]) == pytest.approx(float(flat_scene[on_block]), rel=1e-5)


def test_light_in_front_keeps_solid_shadows_however_tall_the_shape() -> None:
    depth = np.full((H, W), 0.1, dtype=np.float32)
    depth[:, 25:30] = 1.0
    low_front = Light(x=0.05, y=0.5, z=0.06, specular=0.0, diffusion=0.0,
                      cast_shadows=True, shadow_strength=1.0)
    assert shading.light_embed(low_front, torch.from_numpy(depth), H / W) < 0  # over the floor
    assert float(lit(low_front, depth=depth)[H // 2, 40, 0]) == pytest.approx(0.0, abs=1e-6)


def test_directional_light_counts_as_behind_only_when_it_shines_from_the_back() -> None:
    depth = torch.from_numpy(FLAT)
    front = Light(type="directional", x=0.2, y=0.5, z=1.0)
    back = Light(type="directional", x=0.2, y=0.5, z=0.02)  # below its target height
    assert shading.light_embed(front, depth, H / W) == -1000.0
    assert shading.light_embed(back, depth, H / W) == 1000.0


def test_shadow_strength_scales_the_darkening() -> None:
    depth = np.full((H, W), 0.1, dtype=np.float32)
    depth[:, 25:30] = 1.0
    lamp = dict(x=0.05, y=0.5, z=0.2, specular=0.0, diffusion=0.0)
    full = lit(Light(**lamp), depth=depth)[H // 2, 40, 0]  # type: ignore[arg-type]
    half = lit(Light(**lamp, cast_shadows=True, shadow_strength=0.5), depth=depth)[H // 2, 40, 0]  # type: ignore[arg-type]
    assert float(half) == pytest.approx(float(full) * 0.5, rel=1e-4)


def test_disabled_lights_and_lights_past_the_limit_are_ignored() -> None:
    on, off = Light(intensity=0.2), Light(intensity=0.2, enabled=False)
    one = shade(GREY, FACING, FLAT, [on], NO_BASE).relit
    assert torch.equal(shade(GREY, FACING, FLAT, [off, on], NO_BASE).relit, one)
    ten = shade(GREY, FACING, FLAT, [on] * 10, NO_BASE)
    assert len(ten.per_light) == shading.MAX_LIGHTS


def test_relit_is_base_plus_light_layer_and_exposure_doubles() -> None:
    dim = Light(intensity=0.3, specular=0.0)
    settings = GlobalSettings(keep_original_light=0.5, ambient=0.1)
    result = shade(GREY, FACING, FLAT, [dim], settings)
    base = shading.srgb_to_linear(torch.from_numpy(GREY)) * 0.6
    assert torch.allclose(result.relit, base + result.light_layer, atol=1e-6)
    assert torch.allclose(result.per_light[0], result.light_layer)

    brighter = shade(GREY, FACING, FLAT, [dim],
                     GlobalSettings(keep_original_light=0.5, ambient=0.1, exposure=1.0))
    assert float(brighter.relit.max()) < shading.SOFT_CLIP_START  # still in the linear part
    assert torch.allclose(brighter.relit, result.relit * 2.0, atol=1e-6)


def test_soft_clip_is_identity_then_rolls_off_below_one() -> None:
    values = torch.tensor([0.0, 0.3, 0.8, 1.0, 5.0, 100.0])
    clipped = soft_clip(values)
    assert torch.equal(clipped[:3], values[:3])
    assert bool((clipped[3:] < 1.0001).all()) and bool((clipped[3:] > 0.8).all())
    assert bool((clipped[1:] >= clipped[:-1]).all())  # never decreases


def test_light_from_app_json() -> None:
    light = Light.from_json({
        "id": "a", "name": "Key", "enabled": False, "type": "spot",
        "position": {"x": 0.1, "y": 0.2, "z": 0.9}, "target": {"x": 0.6, "y": 0.7},
        "color": [1, 0.5, 0.25], "intensity": 2, "diffusion": 0.4, "radius": 1.2,
        "specular": 0.3, "shininess": 50, "coneAngle": 35, "coneSoftness": 0.6,
        "castShadows": True, "shadowStrength": 0.8,
    })
    assert light == Light(
        type="spot", x=0.1, y=0.2, z=0.9, target_x=0.6, target_y=0.7, color=(1.0, 0.5, 0.25),
        intensity=2.0, diffusion=0.4, radius=1.2, specular=0.3, shininess=50.0, cone_angle=35.0,
        cone_softness=0.6, cast_shadows=True, shadow_strength=0.8, enabled=False,
    )
    settings = GlobalSettings.from_json({"ambient": 0.2, "exposure": -1, "keepOriginalLight": 0.4})
    assert settings == GlobalSettings(ambient=0.2, exposure=-1.0, keep_original_light=0.4)
