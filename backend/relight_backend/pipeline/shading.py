"""Reference implementation of the live-preview shading.

This must compute the same picture as the WebGL shader in
app/src/renderer/src/gl/shader.ts. The shared numbers live in SHADING in
app/src/shared/lighting.ts; tests/test_shading.py checks the two files agree,
and scripts/parity.py compares the rendered pixels.

Space: x = u (0 at the left edge, 1 at the right), y = (1 - v) * aspect (up),
z = DEPTH_SCALE * depth (toward the viewer). Everything is in image-width
units. All colour math is in linear light.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from relight_backend.constants import DEPTH_SCALE
from relight_backend.utils.image_io import FloatArray

MAX_LIGHTS = 8
WRAP_K = 1.0  # diffusion 1 gives half-Lambert wrap
SPEC_FADE = 0.1  # specular fades out as the surface turns away from the light
SHADOW_BIAS = 0.006
SHADOW_SOFT_MIN = 0.012  # penumbra width (height units) at diffusion 0
SHADOW_SOFT_MAX = 0.08  # ... and at diffusion 1
SHADOW_REACH = 1.0  # how far a directional light's shadow ray travels
SHADOW_THICKNESS = 0.15  # most a shape's shell counts as, for lights behind the surface
# The march samples a blurred copy of the height map (a mip level), as wide as the
# step it takes: no shape can fall between two samples, so shadow edges come out
# clean instead of dotted. Steps are short near the lit point and long far away,
# so a shadow is crisp where it touches and soft at a distance.
SHADOW_LOD_SCALE = 2.0  # blur width, in multiples of the step length
SHADOW_SPREAD = 0.35  # extra blur per unit of distance travelled, times the light's diffusion
SHADOW_MAX_LOD = 10  # most mip levels kept (fewer when the map runs out first)
# The subject is not a wall reaching back to the horizon: it is about as deep as
# it is wide. Its thickness map says so (see thickness_code); 0 there means solid.
THICKNESS_SCALE = 0.1  # the thickness whose code is 0.5
THICKNESS_PER_WIDTH = 1.6  # thickness per unit of distance from the subject's outline
THICKNESS_MIN = 0.03
THICKNESS_MAX = 0.1
THICKNESS_CODE_MIN = 0.25  # codes above this are subject (real ones are 0.5 and up)
SUBJECT_GROW = 0.005  # the subject is widened by this much, as a fraction of the map width
SUBJECT_MAX_SHARE = 0.9  # a "subject" covering more of the picture than this is no subject
EMBED_FADE = 0.03  # how gradually a light counts as "behind" as it sinks under the surface
SHELL_DILATE = 0.004  # radius of the "top nearby" filter, as a fraction of the map width
RIM_STRENGTH = 1.5  # brightness of the outline glow from a light behind a shape
RIM_EDGE_SCALE = 0.08  # depth step that counts as a full outline
RIM_WHITE = 0.35  # how much of the rim is the light's own colour rather than the surface's
RIM_WIDTH = 0.0015  # pixel unit of the outline's width, as a fraction of the map width
RIM_REACH = (1, 2, 3, 4)  # distances of the outline map, in multiples of that unit
# "Even out original light": lights act on the photo's colours scaled toward a
# mid-grey exposure, so they do not just multiply the lighting already in it.
FLATTEN_TARGET = 0.18  # the brightness regions are scaled toward
FLATTEN_FLOOR = 0.02  # regions darker than this are treated as this bright
FLATTEN_MAX = 4.0  # never brighten by more than this
# Under a light nothing is perfectly black: surfaces count as at least this bright
# (times the Even light amount), so coloured light shows on dark backgrounds.
# Kept small: at 0.06 a strong spotlight turned black cloth mid-grey.
ALBEDO_FLOOR = 0.02
SOFT_CLIP_START = 0.8  # values above this are rolled off toward 1
TARGET_HEIGHT = 0.5  # spot/directional lights aim at this fraction of DEPTH_SCALE
DEFAULT_SHADOW_STEPS = 40

Tensor = torch.Tensor


@dataclass(frozen=True)
class Light:
    type: str = "point"  # "point" | "directional" | "spot"
    x: float = 0.5  # normalized image coords, y down
    y: float = 0.5
    z: float = 0.7  # height above the image plane (z = 0), image-width units
    target_x: float = 0.5  # where directional/spot lights aim
    target_y: float = 0.5
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)  # linear RGB
    intensity: float = 1.5
    diffusion: float = 0.3
    radius: float = 0.8
    specular: float = 0.0
    shininess: float = 32.0
    cone_angle: float = 50.0  # full angle, degrees
    cone_softness: float = 0.5
    cast_shadows: bool = False
    shadow_strength: float = 0.7
    enabled: bool = True
    name: str = "Light"  # only used to name exported files

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Light:
        """Build from the app's JSON (camelCase, nested position/target)."""
        position, target = data["position"], data.get("target", {"x": 0.5, "y": 0.5})
        return cls(
            type=data["type"],
            x=float(position["x"]),
            y=float(position["y"]),
            z=float(position["z"]),
            target_x=float(target["x"]),
            target_y=float(target["y"]),
            color=(float(data["color"][0]), float(data["color"][1]), float(data["color"][2])),
            intensity=float(data["intensity"]),
            diffusion=float(data["diffusion"]),
            radius=float(data["radius"]),
            specular=float(data["specular"]),
            shininess=float(data["shininess"]),
            cone_angle=float(data["coneAngle"]),
            cone_softness=float(data["coneSoftness"]),
            cast_shadows=bool(data["castShadows"]),
            shadow_strength=float(data["shadowStrength"]),
            enabled=bool(data.get("enabled", True)),
            name=str(data.get("name", "Light")),
        )


@dataclass(frozen=True)
class GlobalSettings:
    ambient: float = 0.0  # 0..2, flat fill light
    exposure: float = 0.0  # stops
    keep_original_light: float = 1.0  # 0..1
    smoothing: float = 0.0  # 0..1, how far normals lean toward their blurred version
    flatten: float = 0.0  # 0..1, "even out original light" (see FLATTEN_TARGET)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> GlobalSettings:
        return cls(
            ambient=float(data["ambient"]),
            exposure=float(data["exposure"]),
            keep_original_light=float(data["keepOriginalLight"]),
            smoothing=float(data.get("smoothing", 0.0)),
            flatten=float(data.get("flatten", 0.0)),
        )


@dataclass
class Shaded:
    """Linear-light results, already exposed and soft-clipped. Shape (H, W, 3)."""

    relit: Tensor
    light_layer: Tensor  # sum of all light contributions, without the base image
    per_light: list[Tensor] = field(default_factory=list)
    base: Tensor | None = None  # the image with the scene settings but no lights
    # Per-light contributions, exposed but NOT soft-clipped (for splitting a layer by light).
    raw_per_light: list[Tensor] = field(default_factory=list)


def srgb_to_linear(value: Tensor) -> Tensor:
    return torch.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(value: Tensor) -> Tensor:
    value = value.clamp(0.0, 1.0)
    return torch.where(value <= 0.0031308, value * 12.92, 1.055 * value ** (1.0 / 2.4) - 0.055)


def soft_clip(value: Tensor) -> Tensor:
    """Identity up to SOFT_CLIP_START, then a smooth roll-off that never passes 1."""
    span = 1.0 - SOFT_CLIP_START
    rolled = SOFT_CLIP_START + span * torch.tanh((value - SOFT_CLIP_START) / span)
    return torch.where(value <= SOFT_CLIP_START, value, rolled)


def _smoothstep(edge0: float, edge1: float, value: Tensor) -> Tensor:
    t = ((value - edge0) / (edge1 - edge0)).clamp(0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _fract(value: Tensor) -> Tensor:
    return value - torch.floor(value)


def pixel_noise(
    height: int, width: int, device: torch.device, rows: tuple[int, int] | None = None
) -> Tensor:
    """Interleaved gradient noise in [0, 1), indexed like gl_FragCoord (origin bottom-left).

    `rows` limits the result to rows [start, end) of the image.
    """
    start, end = rows or (0, height)
    frag_x = torch.arange(width, device=device, dtype=torch.float32) + 0.5
    frag_y = (height - 1 - torch.arange(start, end, device=device, dtype=torch.float32)) + 0.5
    dotted = frag_x[None, :] * 0.06711056 + frag_y[:, None] * 0.00583715
    return _fract(52.9829189 * _fract(dotted))


def light_position(light: Light, aspect: float) -> tuple[float, float, float]:
    return (light.x, (1.0 - light.y) * aspect, light.z)


def light_direction(light: Light, aspect: float) -> tuple[float, float, float]:
    """Unit vector the light travels along: from its position toward its target."""
    px, py, pz = light_position(light, aspect)
    dx = light.target_x - px
    dy = (1.0 - light.target_y) * aspect - py
    dz = DEPTH_SCALE * TARGET_HEIGHT - pz
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
    return (dx / length, dy / length, dz / length)


def cone_cosines(light: Light) -> tuple[float, float]:
    """(cos of the outer edge, cos of the inner edge) of a spot light's cone."""
    half = math.radians(light.cone_angle) / 2.0
    softness = min(max(light.cone_softness, 0.01), 1.0)
    return (math.cos(half), math.cos(half * (1.0 - softness)))


def light_embed(light: Light, depth: Tensor, aspect: float) -> float:
    """How far a light is below the photo's surface at its own spot (> 0 = behind it).

    A directional light has no spot: +-1000 by whether it shines from behind.
    Same rule as lightEmbed() in the app's gl/renderer.ts.
    """
    if light.type == "directional":
        return 1000.0 if light_direction(light, aspect)[2] > 0 else -1000.0
    height, width = depth.shape
    column = min(width - 1, max(0, math.floor(light.x * width)))
    row = min(height - 1, max(0, math.floor(light.y * height)))
    return DEPTH_SCALE * float(depth[row, column]) - light.z


def dilate_radius(width: int) -> int:
    """Radius, in pixels, of the "top nearby" filter. Same as dilateRadius() in the app."""
    return max(1, math.floor(width * SHELL_DILATE + 0.5))


def _window_max(values: Tensor, radius: int) -> Tensor:
    """Highest value within a square window of 2 * radius + 1.

    Done along rows, then columns: the same result as one square window, at a
    cost that grows with the radius instead of its square (matters at full size).
    """
    size = 2 * radius + 1
    rows = F.max_pool2d(values[None, None], (1, size), stride=1, padding=(0, radius))
    return F.max_pool2d(rows, (size, 1), stride=1, padding=(radius, 0))[0, 0]


def dilate_depth(depth: Tensor) -> Tensor:
    """Highest depth within dilate_radius pixels of each pixel."""
    return _window_max(depth, dilate_radius(depth.shape[1]))


def rim_radius(width: int) -> int:
    """Pixel unit of the outline's width. Same as rimRadius() in the app."""
    return max(1, math.floor(width * RIM_WIDTH + 0.5))


def outline_map(depth: Tensor) -> Tensor:
    """Outline strength, 0..1: how much a pixel stands above the lowest depth near it.

    Averaged over four distances, so it is 1 right on the near side of a depth
    edge and fades over a few pixels inward. Same as outlineMap() in the app.
    """
    radius = rim_radius(depth.shape[1])
    outline = torch.zeros_like(depth)
    for reach in RIM_REACH:
        lowest = -_window_max(-depth, reach * radius)
        outline = outline + ((depth - lowest) / RIM_EDGE_SCALE).clamp(0.0, 1.0) / len(RIM_REACH)
    return outline


def thickness_code(mask: FloatArray) -> FloatArray:
    """Where the subject is and how thick, as the 0..1 code the shading reads.

    `mask` is the subject mask (1 = subject). A body part is taken to be about
    as deep as it is wide: thickness grows with the distance from the outline,
    between THICKNESS_MIN and THICKNESS_MAX (image-width units). The code is
    THICKNESS_SCALE / (thickness + THICKNESS_SCALE), so always above 0.25 on the
    subject; 0 stands for everything else, which is solid all the way back.

    The subject is widened by a few pixels first: the outline in the depth map
    and the outline of the mask never agree exactly, and a rim of subject-high
    depth left on the background would cast a solid shadow of its own.
    """
    inside = (mask > 0.5).astype(np.uint8)
    if float(inside.mean()) > SUBJECT_MAX_SHARE:
        return np.zeros_like(mask, dtype=np.float32)
    from_outline = cv2.distanceTransform(inside, cv2.DIST_L2, 5) / mask.shape[1]
    thickness = np.clip(THICKNESS_PER_WIDTH * from_outline, THICKNESS_MIN, THICKNESS_MAX)
    code = THICKNESS_SCALE / (thickness + THICKNESS_SCALE)
    size = 2 * max(1, round(mask.shape[1] * SUBJECT_GROW)) + 1
    grown = cv2.dilate(inside, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size)))
    return np.asarray(np.where(grown > 0, code, 0.0), dtype=np.float32)


def march_levels(depth: Tensor, thickness: Tensor) -> list[Tensor]:
    """What the shadow march reads, with mip levels: (4, H, W) each.

    Channels: the depth of the background, the share that is subject, the depth
    of the subject, the thickness of the subject; the first is weighted by the
    share that is background and the last two by the share that is subject.
    Averaging such weighted values keeps the two apart: half a blurred pixel
    being subject does not turn into a wall half as high as the subject.
    `thickness` is the code from thickness_code().

    Each level averages 2 x 2 blocks of the one before and has half its size,
    rounded down. Same as marchLevels() in the app's gl/renderer.ts.
    """
    subject = (thickness > THICKNESS_CODE_MIN).to(depth.dtype)
    deep = THICKNESS_SCALE * (1.0 - thickness) / thickness.clamp_min(THICKNESS_CODE_MIN)
    deep = deep.clamp(max=THICKNESS_MAX)
    levels = [torch.stack([(1.0 - subject) * depth, subject, subject * depth, subject * deep])]
    while min(levels[-1].shape[1:]) > 1 and len(levels) <= SHADOW_MAX_LOD:
        last = levels[-1]
        height, width = last.shape[1] // 2, last.shape[2] // 2
        last = last[:, : height * 2, : width * 2]
        levels.append(0.25 * (last[:, 0::2, 0::2] + last[:, 0::2, 1::2]
                              + last[:, 1::2, 0::2] + last[:, 1::2, 1::2]))
    return levels


def _sample_levels(levels: list[Tensor], grid: Tensor, lod: Tensor) -> Tensor:
    """Trilinear lookup: (4, h, w) values at `grid`, each pixel at its own level `lod`."""
    lod = lod.clamp(0.0, len(levels) - 1.0)
    lowest, highest = math.floor(float(lod.min())), math.ceil(float(lod.max()))
    result = torch.zeros((levels[0].shape[0], *lod.shape), device=lod.device)
    for level in range(lowest, highest + 1):
        weight = (1.0 - (lod - level).abs()).clamp(0.0, 1.0)
        values = F.grid_sample(
            levels[level][None], grid, mode="bilinear", padding_mode="border", align_corners=False
        )[0]
        result = result + values * weight
    return result


def _exit(origin: Tensor, direction: Tensor, low: float, high: float) -> Tensor:
    """How far along a ray (in ray lengths) a coordinate leaves the range [low, high]."""
    far = torch.full_like(origin, 1e9)
    up = torch.where(direction > 1e-9, (high - origin) / direction.clamp_min(1e-9), far)
    down = torch.where(direction < -1e-9, (low - origin) / direction.clamp_max(-1e-9), far)
    return torch.minimum(up, down)


def _occlusion(
    position: Tensor, ray: Tensor, levels: list[Tensor], tops: Tensor, aspect: float,
    diffusion: float, jitter: Tensor, steps: int, behind: float, shell_cap: float,
) -> Tensor:
    """How blocked each pixel is, 0..1: march toward the light over the depth heightfield.

    The shapes of the background are solids reaching all the way back. The
    subject is as thick as its thickness map says, and light passes behind it.
    A light behind the surface must itself be in open space, so for it
    (behind = 1) every shape is a shell of at most `shell_cap` and light can
    pass in the gap behind.

    The march covers only the part of the ray that is over the picture and below
    the tallest possible shape, in steps that grow with distance; each sample
    reads the maps blurred to the width of its step (see SHADOW_LOD_SCALE).
    """
    soft = SHADOW_SOFT_MIN + (SHADOW_SOFT_MAX - SHADOW_SOFT_MIN) * diffusion
    width = levels[0].shape[2]
    x, y, z = position[..., 0], position[..., 1], position[..., 2]
    end = torch.minimum(_exit(x, ray[..., 0], 0.0, 1.0), _exit(y, ray[..., 1], 0.0, aspect))
    end = torch.minimum(end, _exit(z, ray[..., 2], -1.0, DEPTH_SCALE + SHADOW_BIAS)).clamp(0.0, 1.0)
    across = torch.sqrt(ray[..., 0] ** 2 + ray[..., 1] ** 2) * end * width  # pixels, over the map
    length = ray.norm(dim=-1) * end
    rise = ray[..., 2].abs() * end

    occluded = torch.zeros_like(x)  # the pixels being shaded (may be a strip)
    for step in range(steps):
        s = (step + 0.5 + jitter) / steps
        t = end * s * s
        sample = position + ray * t[..., None]
        u = sample[..., 0].clamp(0.0, 1.0)
        v = (1.0 - sample[..., 1] / aspect).clamp(0.0, 1.0)
        footprint = torch.maximum(
            SHADOW_LOD_SCALE * across * (2.0 * s / steps),
            SHADOW_SPREAD * diffusion * length * (s * s) * width,
        )
        grid = torch.stack([u * 2.0 - 1.0, v * 2.0 - 1.0], dim=-1)[None]
        ground, share, front, deep = _sample_levels(
            levels, grid, torch.log2(footprint.clamp_min(1.0))
        )
        half_rise = rise * s / steps  # half the height the ray gains over this step
        height = sample[..., 2] + SHADOW_BIAS
        edge = soft + half_rise

        # The background: solid, or a shell when the light is behind the surface.
        below = DEPTH_SCALE * ground / (1.0 - share).clamp_min(1e-4) - height
        blocked = (below / edge).clamp(0.0, 1.0)
        if behind > 0.0:
            # Thickness is counted from the top of the shape nearby, not from the
            # steep wall every outline has in a depth map; else a ray passing
            # under a shape would always hit that wall.
            top = F.grid_sample(tops[None, None], grid, mode="bilinear", padding_mode="border",
                                align_corners=False)[0, 0]
            under = DEPTH_SCALE * top - height - shell_cap - half_rise
            shell = 1.0 - (under / (0.25 * shell_cap + half_rise + 1e-4)).clamp(0.0, 1.0)
            blocked = blocked * (1.0 + (shell - 1.0) * behind)

        # The subject: a slab from its front surface to its thickness behind that.
        inside = DEPTH_SCALE * front / share.clamp_min(1e-4) - height
        thickness = deep / share.clamp_min(1e-4)
        thickness = thickness + (thickness.clamp(max=shell_cap) - thickness) * behind
        slab = 1.0 - ((inside - thickness - half_rise)
                      / (0.25 * thickness + half_rise + 1e-4)).clamp(0.0, 1.0)
        blocked = (1.0 - share) * blocked + share * (inside / edge).clamp(0.0, 1.0) * slab
        occluded = torch.maximum(occluded, blocked)
    return occluded


def _contribution(
    light: Light, albedo: Tensor, normal: Tensor, position: Tensor, depth: Tensor,
    levels: list[Tensor], tops: Tensor, outline: Tensor, aspect: float, noise: Tensor,
    steps: int, jitter: float,
) -> Tensor:
    device = albedo.device
    direction = torch.tensor(light_direction(light, aspect), device=device)

    if light.type == "directional":
        to_light = (-direction).expand_as(position)
        attenuation = torch.ones_like(position[..., 0])
        ray = to_light * SHADOW_REACH
    else:
        ray = torch.tensor(light_position(light, aspect), device=device) - position
        distance = ray.norm(dim=-1)
        to_light = ray / distance.clamp_min(1e-5)[..., None]
        reach = distance / (light.radius * (1.0 + light.diffusion))
        attenuation = 1.0 / (1.0 + reach * reach)

    if light.type == "spot":
        outer, inner = cone_cosines(light)
        attenuation = attenuation * _smoothstep(outer, inner, (-to_light * direction).sum(dim=-1))

    n_dot_l = (normal * to_light).sum(dim=-1)
    wrap = light.diffusion * WRAP_K
    diffuse = ((n_dot_l + wrap) / (1.0 + wrap)).clamp(0.0, 1.0)

    view = torch.tensor([0.0, 0.0, 1.0], device=device)
    half = F.normalize(to_light + view, dim=-1)
    n_dot_h = (normal * half).sum(dim=-1).clamp_min(0.0)
    specular = light.specular * n_dot_h**light.shininess * _smoothstep(0.0, SPEC_FADE, n_dot_l)

    shadow = torch.ones_like(position[..., 0])
    if light.cast_shadows and light.shadow_strength > 0.0:
        embed = light_embed(light, depth, aspect)
        behind = float(_smoothstep(0.0, EMBED_FADE, torch.tensor(embed)))
        # Keep the shell above the light itself, or the light would be inside it.
        shell_cap = min(SHADOW_THICKNESS, 0.7 * max(embed, 0.0))
        occluded = _occlusion(
            position, ray, levels, tops, aspect, light.diffusion, (noise - 0.5) * jitter, steps,
            behind, shell_cap,
        )
        shadow = 1.0 - light.shadow_strength * occluded

    # Rim light: a light behind a shape makes its outline glow. The outline comes
    # from depth edges; squaring keeps it thin and brightest right at the edge. It
    # is not shadowed: the rim is exactly the light that gets past the shape.
    from_behind = _smoothstep(0.0, 0.5, -to_light[..., 2])
    rim = RIM_STRENGTH * from_behind * outline * outline
    rim_colour = albedo + (1.0 - albedo) * RIM_WHITE

    color = torch.tensor(light.color, device=device) * light.intensity
    lit = shadow[..., None] * (albedo * diffuse[..., None] + specular[..., None])
    return color * attenuation[..., None] * (lit + rim[..., None] * rim_colour)


@dataclass
class Scene:
    """The maps, converted once and kept on one device. Shapes (H, W[, 3])."""

    albedo: Tensor  # linear light
    normal: Tensor
    heights: Tensor  # depth 0..1
    tops: Tensor  # highest depth nearby (see dilate_depth)
    outline: Tensor  # see outline_map
    normal_smooth: Tensor  # blurred normals, for the smoothing setting
    reach: Tensor  # 1 where lights reach, 0 for sky and the far distance
    brightness: Tensor  # large-scale linear brightness of the photo
    levels: list[Tensor]  # what the shadow march reads (see march_levels)


def prepare_scene(
    albedo_srgb: FloatArray, normals: FloatArray, depth: FloatArray,
    device: torch.device | None = None,
    tops: FloatArray | None = None, outline: FloatArray | None = None,
    normal_smooth: FloatArray | None = None, reach: FloatArray | None = None,
    brightness: FloatArray | None = None, thickness: FloatArray | None = None,
) -> Scene:
    """Convert float32 maps (the app's map conventions) for shading.

    `tops` and `outline` are derived from the depth when not given. An export
    passes them in, made at the working size and scaled up like the depth itself.
    `thickness` is the code from thickness_code(); without it everything is solid.
    """
    device = device or torch.device("cpu")
    heights = torch.from_numpy(np.ascontiguousarray(depth)).to(device)

    def given(values: FloatArray) -> Tensor:
        return torch.from_numpy(np.ascontiguousarray(values)).to(device)

    normal = F.normalize(given(normals), dim=-1)
    # Without the helper maps: no smoothing, lights reach everywhere, no evening out.
    smooth = normal if normal_smooth is None else F.normalize(given(normal_smooth), dim=-1)
    even = torch.full_like(heights, FLATTEN_TARGET) if brightness is None else given(brightness)
    solid = torch.zeros_like(heights) if thickness is None else given(thickness)
    return Scene(
        albedo=srgb_to_linear(given(albedo_srgb)),
        normal=normal,
        normal_smooth=smooth,
        reach=torch.ones_like(heights) if reach is None else given(reach),
        brightness=even,
        heights=heights,
        tops=dilate_depth(heights) if tops is None else given(tops),
        outline=outline_map(heights) if outline is None else given(outline),
        levels=march_levels(heights, solid),
    )


def shade_scene(
    scene: Scene,
    lights: list[Light],
    settings: GlobalSettings,
    *,
    shadow_steps: int = DEFAULT_SHADOW_STEPS,
    jitter: float = 1.0,
    rows: tuple[int, int] | None = None,
) -> Shaded:
    """Shade the scene, or only rows [start, end) of it.

    A strip gives exactly the pixels the whole image would: shadows still look
    up the full depth map. Large exports go strip by strip to bound memory.
    """
    device = scene.heights.device
    height, width = scene.heights.shape
    start, end = rows or (0, height)
    aspect = height / width

    albedo, normal = scene.albedo[start:end], scene.normal[start:end]
    smooth = scene.normal_smooth[start:end]
    normal = F.normalize(normal + (smooth - normal) * settings.smoothing, dim=-1)
    # What the lights fall on: the photo's colours, evened out toward mid exposure.
    even = FLATTEN_TARGET / scene.brightness[start:end].clamp_min(FLATTEN_FLOOR)
    lit_albedo = albedo * (even**settings.flatten).clamp(max=FLATTEN_MAX)[..., None]
    lit_albedo = lit_albedo.clamp_min(ALBEDO_FLOOR * settings.flatten)
    reach = scene.reach[start:end, :, None]
    u = (torch.arange(width, device=device, dtype=torch.float32) + 0.5) / width
    v = (torch.arange(start, end, device=device, dtype=torch.float32) + 0.5) / height
    position = torch.stack(
        [
            u[None, :].expand(end - start, width),
            ((1.0 - v) * aspect)[:, None].expand(end - start, width),
            DEPTH_SCALE * scene.heights[start:end],
        ],
        dim=-1,
    )
    noise = pixel_noise(height, width, device, (start, end))

    active = [light for light in lights if light.enabled][:MAX_LIGHTS]
    per_light = [
        _contribution(
            light, lit_albedo, normal, position, scene.heights, scene.levels, scene.tops,
            scene.outline[start:end], aspect, noise, shadow_steps, jitter,
        ) * reach
        for light in active
    ]
    light_sum = torch.stack(per_light).sum(dim=0) if per_light else torch.zeros_like(albedo)

    gain = 2.0**settings.exposure
    base = albedo * (settings.keep_original_light + settings.ambient)
    return Shaded(
        relit=soft_clip((base + light_sum) * gain),
        light_layer=soft_clip(light_sum * gain),
        per_light=[soft_clip(layer * gain) for layer in per_light],
        base=soft_clip(base * gain),
        raw_per_light=[layer * gain for layer in per_light],
    )


def shade(
    albedo_srgb: FloatArray,
    normals: FloatArray,
    depth: FloatArray,
    lights: list[Light],
    settings: GlobalSettings,
    *,
    shadow_steps: int = DEFAULT_SHADOW_STEPS,
    jitter: float = 1.0,
    device: torch.device | None = None,
) -> Shaded:
    """Shade at the maps' own resolution. Inputs are float32 in the app's map conventions."""
    scene = prepare_scene(albedo_srgb, normals, depth, device)
    return shade_scene(scene, lights, settings, shadow_steps=shadow_steps, jitter=jitter)


def to_srgb8(linear: Tensor) -> np.ndarray[Any, np.dtype[np.uint8]]:
    """Linear (H, W, 3) to 8-bit sRGB, rounded the way a framebuffer write rounds."""
    encoded = (linear_to_srgb(linear) * 255.0 + 0.5).floor().clamp(0, 255)
    return encoded.to(torch.uint8).cpu().numpy()
