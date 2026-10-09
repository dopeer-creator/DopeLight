"""The Python reference shading: behaviour, and agreement with the app's constants."""

import re
from pathlib import Path

import cv2
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
        "shadowLodScale": shading.SHADOW_LOD_SCALE,
        "shadowSpread": shading.SHADOW_SPREAD,
        "shadowMaxLod": shading.SHADOW_MAX_LOD,
        "thicknessScale": shading.THICKNESS_SCALE,
        "thicknessMax": shading.THICKNESS_MAX,
        "thicknessCodeMin": shading.THICKNESS_CODE_MIN,
        "embedFade": shading.EMBED_FADE,
        "shellDilate": shading.SHELL_DILATE,
        "rimStrength": shading.RIM_STRENGTH,
        "rimWhite": shading.RIM_WHITE,
        "rimBack": shading.RIM_BACK,
        "rimWrap": shading.RIM_WRAP,
        "rimFrontFade": shading.RIM_FRONT_FADE,
        "flattenTarget": shading.FLATTEN_TARGET,
        "flattenFloor": shading.FLATTEN_FLOOR,
        "flattenMax": shading.FLATTEN_MAX,
        "albedoFloor": shading.ALBEDO_FLOOR,
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


def test_thickness_code_marks_the_subject_and_how_deep_it_is() -> None:
    wide = 200
    mask = np.zeros((80, wide), dtype=np.float32)
    mask[10:70, 60:140] = 1.0
    code = shading.thickness_code(mask)
    scale = shading.THICKNESS_SCALE
    assert code[5, 5] == 0.0  # background: solid all the way back
    # Just inside the outline it is as thin as it gets, in the middle as thick as it gets.
    assert code[40, 61] == pytest.approx(scale / (shading.THICKNESS_MIN + scale), abs=0.02)
    assert code[40, 100] == pytest.approx(scale / (shading.THICKNESS_MAX + scale), abs=0.02)
    assert code[40, 59] > shading.THICKNESS_CODE_MIN  # widened by a pixel past the mask
    # No subject to speak of: nothing is marked.
    assert float(shading.thickness_code(np.ones((80, wide), dtype=np.float32)).max()) == 0.0


def test_march_levels_keep_subject_and_background_apart() -> None:
    depth = torch.full((8, 8), 0.2)
    depth[:, 4:] = 0.9  # the subject: the right half, much nearer
    code = torch.zeros((8, 8))
    code[:, 4:] = 0.5  # thickness = THICKNESS_SCALE
    levels = shading.march_levels(depth, code)
    assert [tuple(level.shape[1:]) for level in levels] == [(8, 8), (4, 4), (2, 2), (1, 1)]
    ground, share, front, deep = levels[-1][:, 0, 0]  # everything averaged into one value
    assert float(share) == pytest.approx(0.5)
    # Divided by their shares, both depths come back whole: not one wall of middling height.
    assert float(ground / (1.0 - share)) == pytest.approx(0.2)
    assert float(front / share) == pytest.approx(0.9)
    assert float(deep / share) == pytest.approx(shading.THICKNESS_SCALE)


def test_subject_casts_a_shadow_but_light_passes_behind_it() -> None:
    """A slab standing in front of a far wall, lit from the left at its own height."""
    wide, high = 120, 60
    depth = np.full((high, wide), 0.05, dtype=np.float32)  # the wall, far back
    mask = np.zeros((high, wide), dtype=np.float32)
    mask[10:50, 50:70] = 1.0
    depth[10:50, 50:70] = 0.9  # the subject: z = 0.36, at most 0.1 thick
    grey = np.full((high, wide, 3), 0.5, dtype=np.float32)
    facing = np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (high, wide, 1))
    lamp = dict(x=0.02, y=0.5, z=0.36, specular=0.0, diffusion=0.0, radius=3.0)

    def lit_with(thickness: np.ndarray | None, shadows: bool) -> torch.Tensor:
        scene = shading.prepare_scene(grey, facing, depth, thickness=thickness)
        light = Light(**lamp, cast_shadows=shadows, shadow_strength=1.0)  # type: ignore[arg-type]
        return shading.shade_scene(scene, [light], NO_BASE, jitter=0.0).relit

    open_wall = lit_with(None, False)
    solid = lit_with(None, True)  # no thickness map: the subject reaches back to the wall
    slab = lit_with(shading.thickness_code(mask), True)
    wall_behind = (30, 100, 0)  # on the wall, on the far side of the subject from the light
    assert float(open_wall[wall_behind]) > 0.0
    assert float(solid[wall_behind]) == pytest.approx(0.0, abs=1e-6)
    # The light is level with the slab; the wall is far behind it, and the ray to it
    # passes behind the slab's back face.
    assert float(slab[wall_behind]) == pytest.approx(float(open_wall[wall_behind]), rel=0.02)


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
    assert float(result[edge]) > 0.02  # the block's outline glows
    assert float(result[centre]) == 0.0  # its middle does not
    strength = np.linalg.norm(shading.rim_field(depth), axis=-1)
    assert strength[edge[0], edge[1]] > 0.6 and strength[centre[0], centre[1]] == 0.0
    assert strength[floor_far[0], floor_far[1]] == 0.0  # the low side of an edge has none


def test_rim_lights_only_the_edge_that_faces_the_light() -> None:
    depth = np.full((H, W), 0.1, dtype=np.float32)
    depth[10:30, 20:40] = 1.0
    # Level with the top of the block and far off to the right: a side light.
    side = Light(x=3.0, y=0.5, z=0.4, specular=0.0, diffusion=0.0, radius=3.0)
    result = lit(side, depth=depth)
    left_edge, right_edge = (H // 2, 20, 0), (H // 2, 39, 0)
    assert float(result[right_edge]) > 0.05
    assert float(result[left_edge]) == 0.0


def test_rim_map_follows_the_subject_mask_and_points_outward() -> None:
    depth = np.full((H, W), 0.1, dtype=np.float32)
    depth[10:30, 22:38] = 1.0  # the depth map's edge sits two pixels inside the mask's
    mask = np.zeros((H, W), dtype=np.float32)
    mask[10:30, 20:40] = 1.0
    rim = shading.rim_field(depth, mask)
    strength = np.linalg.norm(rim, axis=-1)
    assert strength[H // 2, 20] > 0.6 and strength[H // 2, 39] > 0.6  # at the mask's edge
    assert strength[H // 2, W // 2] == 0.0 and strength[2, 2] == 0.0
    assert rim[H // 2, 20, 0] < 0 < rim[H // 2, 39, 0]  # left edge points left, right edge right
    assert rim[10, W // 2, 1] > 0 > rim[29, W // 2, 1]  # top edge points up, bottom edge down


def test_a_thin_part_gets_a_thinner_rim_than_a_thick_one() -> None:
    wide = 200
    mask = np.zeros((80, wide), dtype=np.float32)
    mask[10:70, 20:80] = 1.0  # a torso, 60 pixels across
    mask[10:70, 120:126] = 1.0  # a finger, 6 pixels across
    mask[66:70, 80:120] = 1.0  # joined to the torso: a piece on its own would count as a stray
    from_edge = cv2.distanceTransform((mask > 0.5).astype(np.uint8), cv2.DIST_L2, 5)
    radius = shading.local_radius(from_edge.astype(np.float32), wide * shading.RIM_RADIUS)
    assert radius[40, 50] == pytest.approx(wide * shading.RIM_RADIUS)  # capped
    assert radius[40, 122] == pytest.approx(3.0, abs=0.5)  # half the finger's width
    assert radius[5, 5] == 0.0  # nothing outside the shape

    turn = np.linalg.norm(shading.rim_field(np.full((80, wide), 0.5, dtype=np.float32), mask),
                          axis=-1)
    # Three pixels in from the right-hand edge of each: the torso is still turning
    # away there, the finger already faces the viewer.
    assert turn[40, 77] > turn[40, 123] + 0.25
    assert turn[40, 79] > 0.85 and turn[40, 125] > 0.85  # both are edge-on at the outline


def test_rim_ignores_strays_and_uncertain_parts_of_the_mask() -> None:
    wide = 200
    mask = np.zeros((80, wide), dtype=np.float32)
    mask[10:70, 20:80] = 1.0  # the subject
    mask[5:20, 150:170] = 1.0  # a stray patch, a twelfth of its size
    flat = np.full((80, wide), 0.5, dtype=np.float32)
    turn = np.linalg.norm(shading.rim_field(flat, mask), axis=-1)
    assert turn[40, 79] > 0.85  # the subject's edge
    assert turn[5:20, 150:170].max() == 0.0  # no outline around the stray

    # The same subject, but its right half is a cloud of greys: the mask model was guessing.
    rng = np.random.default_rng(5)
    unsure = mask.copy()
    unsure[10:70, 50:110] = cv2.GaussianBlur(
        rng.uniform(0.0, 1.0, (60, 60)).astype(np.float32), (0, 0), 2.0
    )
    turn = np.linalg.norm(shading.rim_field(flat, unsure), axis=-1)
    assert turn[40, 20] > 0.85  # the clean left edge still has its rim
    assert turn[20:60, 60:100].max() < 0.1  # nothing is traced through the cloud


def test_a_light_behind_and_to_one_side_rims_that_side_of_the_subject() -> None:
    wide = 200
    mask = np.zeros((80, wide), dtype=np.float32)
    mask[10:70, 70:130] = 1.0
    depth = np.where(mask > 0.5, 0.8, 0.1).astype(np.float32)
    scene = shading.prepare_scene(
        np.full((80, wide, 3), 0.5, dtype=np.float32),
        np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (80, wide, 1)), depth,
        rim=shading.rim_field(depth, mask),
    )
    behind_right = Light(x=0.95, y=0.5, z=0.12, specular=0.0, diffusion=0.2, intensity=2.0)
    result = shading.shade_scene(scene, [behind_right], NO_BASE).relit
    right_edge, a_little_in = (40, 129, 0), (40, 124, 0)
    left_edge, middle = (40, 70, 0), (40, 100, 0)
    assert float(result[right_edge]) > 0.3
    assert float(result[right_edge]) > float(result[a_little_in]) > 0.0  # fades inward
    assert float(result[left_edge]) < 0.05 * float(result[right_edge])  # the far side stays dark
    assert float(result[middle]) == 0.0


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


def scene_with(**maps: np.ndarray) -> shading.Scene:
    return shading.prepare_scene(GREY, FACING, FLAT, **maps)  # type: ignore[arg-type]


def test_lights_do_not_reach_the_sky() -> None:
    reach = np.ones((H, W), dtype=np.float32)
    reach[:10] = 0.0  # the top rows are sky
    lamp = [Light(x=0.5, y=0.1, z=0.6)]
    result = shading.shade_scene(scene_with(reach=reach), lamp, GlobalSettings())
    base = shading.srgb_to_linear(torch.from_numpy(GREY))
    assert torch.allclose(result.relit[:10], base[:10])  # sky: untouched
    assert float((result.relit[20] - base[20]).min()) > 0.01  # ground: lit


def test_evening_out_tames_bright_regions_and_lifts_dark_ones() -> None:
    brightness = np.full((H, W), 0.18, dtype=np.float32)
    brightness[:, :20] = 0.8  # already brightly lit
    brightness[:, 40:] = 0.02  # in deep shade
    lamp = [Light(type="directional", z=2.0, intensity=0.3)]  # dim: stays below the soft clip
    scene = scene_with(brightness=brightness)
    plain = shading.shade_scene(scene, lamp, NO_BASE).relit[H // 2, :, 0]
    evened = shading.shade_scene(scene, lamp, GlobalSettings(keep_original_light=0, flatten=1.0)
                                 ).relit[H // 2, :, 0]
    assert float(evened[5]) < float(plain[5])  # bright region gets less
    assert float(evened[30]) == pytest.approx(float(plain[30]), rel=1e-5)  # mid: unchanged
    assert float(evened[55]) == pytest.approx(float(plain[55]) * shading.FLATTEN_MAX, rel=1e-4)


def test_smoothing_blends_toward_the_smooth_normals() -> None:
    tilted = np.tile(np.array([0.8, 0.0, 0.6], dtype=np.float32), (H, W, 1))
    scene = shading.prepare_scene(GREY, tilted, FLAT, normal_smooth=FACING)
    lamp = [Light(type="directional", x=0.5, y=0.5, z=2.0, diffusion=0.0)]  # straight on
    values = [float(shading.shade_scene(
        scene, lamp, GlobalSettings(keep_original_light=0, smoothing=amount)).relit[5, 5, 0])
        for amount in (0.0, 0.5, 1.0)]
    assert values[0] < values[1] < values[2]


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
        cone_softness=0.6, cast_shadows=True, shadow_strength=0.8, enabled=False, name="Key",
    )
    settings = GlobalSettings.from_json({"ambient": 0.2, "exposure": -1, "keepOriginalLight": 0.4})
    assert settings == GlobalSettings(ambient=0.2, exposure=-1.0, keep_original_light=0.4)
