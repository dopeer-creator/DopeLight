"""Parity check: does the WebGL shader draw the same picture as the Python reference?

    npm run parity

Builds a synthetic fixture (albedo, normals, depth) and a set of scenes, has
Electron render them with the real shader (headless), renders the same scenes
with relight_backend.pipeline.shading, and compares the 8-bit results.
Side-by-side images (Python | WebGL | difference x16) land in parity-out/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))  # this script lives outside the backend package

from relight_backend.pipeline.normals_from_depth import normals_from_depth  # noqa: E402
from relight_backend.pipeline.preprocess import (  # noqa: E402
    large_scale_brightness,
    smooth_normals,
)
from relight_backend.pipeline.shading import (  # noqa: E402
    GlobalSettings,
    Light,
    prepare_scene,
    rim_field,
    shade_scene,
    srgb_to_linear,
    to_srgb8,
)
from relight_backend.utils.image_io import (  # noqa: E402
    load_aux,
    load_normals,
    save_aux,
    save_normals,
)

OUT = ROOT / "parity-out"
WIDTH, HEIGHT = 320, 200

# 8-bit levels. Shadow edges and specular peaks amplify tiny float differences
# between GPU and CPU, so a few pixels may differ by more than the mean suggests.
MAX_MEAN_DIFF = 0.5
MAX_FRACTION_OVER_3 = 0.005


def build_maps() -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    """Albedo (uint8 RGB), normals (float, via 8-bit PNG), depth (uint16), helper maps."""
    xs, ys = np.meshgrid(np.linspace(0, 1, WIDTH), np.linspace(0, 1, HEIGHT))

    # A sloped floor, a dome, and a box whose hard edges give shadows something to catch.
    depth = 0.15 + 0.1 * xs
    dome = ((xs - 0.35) / 0.18) ** 2 + ((ys - 0.5) / 0.28) ** 2
    depth = depth + 0.6 * np.sqrt(np.clip(1.0 - dome, 0.0, 1.0))
    box = (xs > 0.62) & (xs < 0.82) & (ys > 0.3) & (ys < 0.7)
    depth = np.where(box, 0.75, depth)
    depth16 = np.clip(depth * 65535.0 + 0.5, 0, 65535).astype(np.uint16)

    checker = np.where((np.floor(xs * 10) + np.floor(ys * 6)) % 2 == 0, 1.0, 0.7)
    albedo = np.dstack([
        0.2 + 0.7 * xs,
        0.25 + 0.6 * ys,
        0.5 + 0.4 * np.sin(8 * xs) * np.cos(6 * ys),
    ]) * checker[..., None]
    albedo8 = np.clip(albedo * 255.0 + 0.5, 0, 255).astype(np.uint8)

    # Round-trip through the PNGs so both sides read the very same 8-bit values.
    save_normals(normals_from_depth((depth16 / 65535.0).astype(np.float32)), OUT / "normal.png")
    normals = load_normals(OUT / "normal.png")
    save_normals(smooth_normals(normals), OUT / "normal_smooth.png")
    # The top-right corner is "sky": lights fade out there.
    reach = np.clip(((1.0 - xs) + ys - 0.35) / 0.15, 0.0, 1.0).astype(np.float32)
    Image.fromarray(albedo8, mode="RGB").save(OUT / "albedo.png")
    # The box is the "subject": its rim follows a mask. Without it only depth edges would.
    rim = rim_field((depth16 / 65535.0).astype(np.float32), box.astype(np.float32))
    save_aux(reach, large_scale_brightness(Image.open(OUT / "albedo.png")), OUT / "aux.png", rim)
    reach8, brightness, rim8 = load_aux(OUT / "aux.png")
    helpers = {"normal_smooth": load_normals(OUT / "normal_smooth.png"), "reach": reach8,
               "brightness": brightness, "rim": rim8}
    return albedo8, normals, depth16, helpers


def light(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "x", "name": "x", "enabled": True, "type": "point",
        "position": {"x": 0.3, "y": 0.3, "z": 0.7}, "target": {"x": 0.5, "y": 0.5},
        "color": [1.0, 0.86, 0.68], "intensity": 1.5, "diffusion": 0.3, "radius": 0.8,
        "specular": 0.2, "shininess": 32, "coneAngle": 50, "coneSoftness": 0.5,
        "castShadows": False, "shadowStrength": 0.7,
    }
    return {**base, **overrides}


def scene(name: str, lights: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name, "lights": lights, "mode": "relit", "split": None,
        "globals": {"ambient": 0.0, "exposure": 0.0, "keepOriginalLight": 1.0,
                    "smoothing": 0.0, "flatten": 0.0},
        "shadowSteps": 24, "jitter": 1.0,
    }
    return {**base, **overrides}


def build_scenes() -> list[dict[str, Any]]:
    low = {"x": 0.08, "y": 0.2, "z": 0.45}
    shadow = light(position=low, castShadows=True, shadowStrength=0.9, diffusion=0.1)
    eight = [
        light(
            type=("point", "spot", "directional")[i % 3],
            position={"x": 0.1 + 0.11 * i, "y": 0.15 + 0.09 * ((i * 3) % 8), "z": 0.3 + 0.15 * i},
            target={"x": 0.9 - 0.1 * i, "y": 0.5},
            color=[0.3 + 0.08 * i, 1.0 - 0.09 * i, 0.5 + 0.05 * ((i * 5) % 8)],
            intensity=0.4 + 0.1 * i, diffusion=0.12 * i, radius=0.3 + 0.2 * i,
            specular=0.1 * i, shininess=8 + 20 * i, coneAngle=30 + 12 * i,
            castShadows=i % 2 == 0, shadowStrength=0.5 + 0.05 * i,
        )
        for i in range(8)
    ]
    return [
        scene("no_lights", []),
        scene("point", [light()]),
        scene("point_soft_glossy", [light(diffusion=0.9, specular=0.8, shininess=60,
                                          position={"x": 0.7, "y": 0.2, "z": 1.2})]),
        scene("directional", [light(type="directional", position={"x": 0.05, "y": 0.1, "z": 0.9},
                                    target={"x": 0.6, "y": 0.6})]),
        scene("spot", [light(type="spot", coneAngle=40, coneSoftness=0.3, intensity=3.0,
                             position={"x": 0.8, "y": 0.15, "z": 0.9},
                             target={"x": 0.4, "y": 0.5})]),
        scene("shadow_no_jitter", [shadow], jitter=0.0),
        scene("shadow_jitter", [shadow]),
        scene("shadow_soft_48_steps", [light(position=low, castShadows=True, diffusion=0.8)],
              shadowSteps=48),
        scene("shadow_directional", [light(type="directional", castShadows=True,
                                           position={"x": 0.0, "y": 0.5, "z": 0.6},
                                           target={"x": 0.7, "y": 0.5})]),
        # Lights behind the surface: sealed inside the dome (stays dark), behind the box
        # (light escapes around it), just under the surface, and a sun from the back.
        scene("back_light_under_dome", [light(position={"x": 0.35, "y": 0.5, "z": 0.16},
                                              castShadows=True, shadowStrength=1.0,
                                              intensity=3.0)]),
        scene("back_light_under_box", [light(position={"x": 0.72, "y": 0.5, "z": 0.12},
                                             castShadows=True, shadowStrength=1.0,
                                             intensity=3.0, diffusion=0.5)]),
        scene("back_light_barely_behind", [light(position={"x": 0.7, "y": 0.5, "z": 0.29},
                                                 castShadows=True, shadowStrength=1.0)]),
        scene("back_sun", [light(type="directional", castShadows=True, intensity=2.0,
                                 position={"x": 0.9, "y": 0.5, "z": 0.02},
                                 target={"x": 0.3, "y": 0.5})]),
        # Rim light: beside the box at its own height, and a soft one behind it.
        scene("rim_side", [light(position={"x": 1.1, "y": 0.5, "z": 0.3}, intensity=3.0,
                                 diffusion=0.1)]),
        scene("rim_behind_soft", [light(position={"x": 0.9, "y": 0.2, "z": 0.05}, intensity=3.0,
                                        diffusion=0.8)]),
        scene("eight_lights", eight),
        scene("globals", [light()],
              globals={"ambient": 0.4, "exposure": 0.7, "keepOriginalLight": 0.5,
                       "smoothing": 0.0, "flatten": 0.0}),
        scene("smooth_and_even", [light(), light(position={"x": 0.8, "y": 0.3, "z": 0.6},
                                                 castShadows=True)],
              globals={"ambient": 0.0, "exposure": 0.0, "keepOriginalLight": 1.0,
                       "smoothing": 0.6, "flatten": 0.7}),
        scene("fully_smooth_and_even", [light(specular=0.6)],
              globals={"ambient": 0.0, "exposure": 0.0, "keepOriginalLight": 0.4,
                       "smoothing": 1.0, "flatten": 1.0}),
        scene("dark_base", [light(intensity=4.0)],
              globals={"ambient": 0.0, "exposure": -1.0, "keepOriginalLight": 0.0,
                       "smoothing": 0.0, "flatten": 0.0}),
        scene("light_only", [light(), light(position={"x": 0.8, "y": 0.7, "z": 0.5},
                                            color=[0.55, 0.72, 1.0])], mode="lightOnly"),
        scene("disabled_light", [light(enabled=False, intensity=5.0), light()]),
        scene("original", [light()], mode="original"),
    ]


def render_python(item: dict[str, Any], albedo: np.ndarray, normals: np.ndarray,
                  depth16: np.ndarray, helpers: dict[str, np.ndarray]) -> np.ndarray:
    albedo_float = albedo.astype(np.float32) / 255.0
    if item["mode"] == "original":
        import torch

        return to_srgb8(srgb_to_linear(torch.from_numpy(albedo_float)))
    scene_maps = prepare_scene(
        albedo_float, normals, (depth16 / 65535.0).astype(np.float32), **helpers
    )
    shaded = shade_scene(
        scene_maps,
        [Light.from_json(entry) for entry in item["lights"]],
        GlobalSettings.from_json(item["globals"]),
        shadow_steps=item["shadowSteps"], jitter=item["jitter"],
    )
    return to_srgb8(shaded.light_layer if item["mode"] == "lightOnly" else shaded.relit)


def render_webgl(skip_build: bool) -> None:
    app = ROOT / "app"
    if not skip_build:
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        subprocess.run([npm, "run", "build"], cwd=app, check=True, stdout=subprocess.DEVNULL)
    electron = app / "node_modules" / "electron" / "dist" / (
        "electron.exe" if sys.platform == "win32" else "electron"
    )
    subprocess.run(
        [str(electron), str(app)], env={**os.environ, "RELIGHT_PARITY": str(OUT)},
        check=False, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    status_file = OUT / "gl_status.json"
    if not status_file.exists():
        sys.exit("Electron did not finish the parity run (no gl_status.json).")
    status = json.loads(status_file.read_text(encoding="utf-8"))
    if not status["ok"]:
        sys.exit(f"WebGL side failed: {status['error']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="reuse the last app build")
    args = parser.parse_args()

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    albedo, normals, depth16, helpers = build_maps()
    scenes = build_scenes()
    (OUT / "depth.raw").write_bytes(depth16.astype("<u2").tobytes())
    (OUT / "scenes.json").write_text(
        json.dumps({"width": WIDTH, "height": HEIGHT, "scenes": scenes}), encoding="utf-8"
    )

    render_webgl(args.skip_build)

    print(f"{'scene':24} {'mean':>6} {'max':>4} {'>3 levels':>10}  result")
    failed = []
    for item in scenes:
        reference = render_python(item, albedo, normals, depth16, helpers)
        raw = np.frombuffer((OUT / f"gl_{item['name']}.rgba").read_bytes(), dtype=np.uint8)
        webgl = raw.reshape(HEIGHT, WIDTH, 4)[..., :3]
        diff = np.abs(reference.astype(np.int16) - webgl.astype(np.int16))
        mean, worst = float(diff.mean()), int(diff.max())
        over = float((diff.max(axis=-1) > 3).mean())
        ok = mean <= MAX_MEAN_DIFF and over <= MAX_FRACTION_OVER_3
        if not ok:
            failed.append(item["name"])
        print(f"{item['name']:24} {mean:6.3f} {worst:4d} {over:10.2%}  {'ok' if ok else 'FAIL'}")
        sheet = np.hstack([reference, webgl, np.clip(diff * 16, 0, 255).astype(np.uint8)])
        Image.fromarray(sheet, mode="RGB").save(OUT / f"{item['name']}.png")

    print(f"\nLimits: mean <= {MAX_MEAN_DIFF} levels, pixels over 3 levels <= "
          f"{MAX_FRACTION_OVER_3:.1%}. Images: {OUT}")
    if failed:
        sys.exit(f"PARITY FAILED: {', '.join(failed)}")
    print("PARITY OK")


if __name__ == "__main__":
    main()
