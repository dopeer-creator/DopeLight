"""Full-resolution export: files, bit depths, and the "base + layer = relit" promise."""

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from relight_backend.pipeline import export as export_module
from relight_backend.pipeline.export import ExportOptions, export, unique_path
from relight_backend.pipeline.normals_from_depth import normals_from_depth
from relight_backend.pipeline.sessions import SessionMeta, SessionStore, map_file
from relight_backend.pipeline.shading import GlobalSettings, Light
from relight_backend.utils.image_io import load_image_array, save_gray16, save_normals

FULL, WORKING = (96, 64), (48, 32)  # (width, height): the original, and the maps
LIGHTS = [
    Light(name="Key", x=0.3, y=0.3, z=0.7, intensity=0.6, color=(1.0, 0.8, 0.6)),
    Light(name="Rim light!", type="spot", x=0.85, y=0.2, z=0.8, target_x=0.4, target_y=0.6,
          intensity=0.9, color=(0.4, 0.6, 1.0), cast_shadows=True),
    Light(name="Off", enabled=False, intensity=5.0),
]
DEFAULTS = GlobalSettings()


class Quiet:
    def report(self, stage: str, progress: float, message: str = "", **extra: Any) -> None:
        return None

    def check_cancel(self) -> None:
        return None


def make_session(root: Path) -> tuple[SessionStore, str, np.ndarray]:
    """A finished session with real maps. Returns the store, the id, and the original pixels."""
    xs, ys = np.meshgrid(np.linspace(0, 1, FULL[0]), np.linspace(0, 1, FULL[1]))
    # Mid-range values: below the soft-clip start, so base == original at default settings.
    original = np.dstack([40 + 120 * xs, 60 + 100 * ys, 150 - 90 * xs * ys]).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(original, mode="RGB").save(buffer, format="PNG")

    store = SessionStore(root)
    root.mkdir(parents=True, exist_ok=True)
    session_id = store.create(buffer.getvalue())
    folder = root / session_id

    mx, my = np.meshgrid(np.linspace(0, 1, WORKING[0]), np.linspace(0, 1, WORKING[1]))
    depth = (0.2 + 0.6 * np.exp(-((mx - 0.5) ** 2 + (my - 0.5) ** 2) / 0.05)).astype(np.float32)
    save_gray16(depth, folder / map_file("depth", "depth"))
    save_normals(normals_from_depth(depth), folder / map_file("normal", "depth"))
    store.save_meta(SessionMeta(session_id, "photo.png", FULL, WORKING, "depth", "stub"))
    return store, session_id, original


@pytest.fixture
def session(tmp_path: Path) -> tuple[SessionStore, str, np.ndarray, Path]:
    store, session_id, original = make_session(tmp_path / "sessions")
    out = tmp_path / "out"
    out.mkdir()
    return store, session_id, original, out


def run(session: Any, name: str, settings: GlobalSettings = DEFAULTS, **options: Any) -> list[Path]:
    store, session_id, _original, out = session
    chosen = ExportOptions(**options)
    return export(store, session_id, LIGHTS, settings, chosen, out / name, Quiet())


def to16(array: np.ndarray) -> np.ndarray:
    return array.astype(np.int64) * 257 if array.dtype == np.uint8 else array.astype(np.int64)


def linear(values16: np.ndarray) -> np.ndarray:
    v = values16 / 65535.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def test_relit_image_is_full_size_and_changed(session: Any) -> None:
    (path,) = run(session, "photo_relit.png", kind="relit")
    relit = load_image_array(path)
    assert path.name == "photo_relit.png"
    assert relit.shape == (FULL[1], FULL[0], 3) and relit.dtype == np.uint8
    assert (relit.astype(int) >= session[2].astype(int) - 1).all()  # light only adds
    assert (relit.astype(int) - session[2].astype(int)).max() > 20


def test_layer_added_to_the_original_gives_the_relit_image(session: Any) -> None:
    """The acceptance check: Add blend in a normal (gamma-space) editor."""
    (relit_path,) = run(session, "relit.png", kind="relit", bit_depth=16)
    (layer_path,) = run(session, "light.png", kind="light_layer", bit_depth=16)
    relit, layer = load_image_array(relit_path), load_image_array(layer_path)
    assert layer.dtype == np.uint16 and layer.max() > 5000

    rebuilt = to16(session[2]) + layer.astype(np.int64)
    assert np.abs(rebuilt - relit.astype(np.int64)).max() <= 3  # of 65535


def test_linear_layer_adds_up_in_linear_light(session: Any) -> None:
    (relit_path,) = run(session, "relit.png", kind="relit", bit_depth=16)
    (layer_path,) = run(session, "light.png", kind="light_layer", bit_depth=16, blend="linear")
    relit, layer = load_image_array(relit_path), load_image_array(layer_path)
    rebuilt = linear(to16(session[2])) + linear(layer.astype(np.int64))
    assert np.abs(rebuilt - linear(relit.astype(np.int64))).max() < 5e-4


def test_per_light_layers_add_up_to_the_light_layer(session: Any) -> None:
    (layer_path,) = run(session, "light.png", kind="light_layer", bit_depth=16)
    parts = run(session, "lights.png", kind="per_light", bit_depth=16)
    assert [path.name for path in parts] == ["lights_1_Key.png", "lights_2_Rim_light.png"]

    total = sum(load_image_array(path).astype(np.int64) for path in parts)
    assert np.abs(total - load_image_array(layer_path).astype(np.int64)).max() <= len(parts)


def test_alpha_version_shows_the_same_layer_over_black(session: Any) -> None:
    layer_path, alpha_path = run(session, "light.png", kind="light_layer", bit_depth=16, alpha=True)
    layer, rgba = load_image_array(layer_path), load_image_array(alpha_path)
    assert alpha_path.name == "light_alpha.png" and rgba.shape[2] == 4
    over_black = rgba[..., :3].astype(np.float64) * rgba[..., 3:].astype(np.float64) / 65535.0
    assert np.abs(over_black - layer).max() <= 2


def test_changed_scene_settings_write_a_base_image(session: Any) -> None:
    settings = GlobalSettings(keep_original_light=0.5, ambient=0.1, exposure=0.5)
    (relit_path,) = run(session, "relit.png", settings, kind="relit", bit_depth=16)
    layer_path, base_path = run(session, "light.png", settings, kind="light_layer", bit_depth=16)
    assert base_path.name == "light_base.png"
    rebuilt = (load_image_array(base_path).astype(np.int64)
               + load_image_array(layer_path).astype(np.int64))
    assert np.abs(rebuilt - load_image_array(relit_path).astype(np.int64)).max() <= 3


def test_strips_give_the_same_pixels_as_one_pass(
    session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    (whole,) = run(session, "whole.png", kind="relit", bit_depth=16)
    monkeypatch.setattr(export_module, "STRIP_PIXELS", FULL[0] * 5)  # five rows at a time
    (strips,) = run(session, "strips.png", kind="relit", bit_depth=16)
    assert np.array_equal(load_image_array(whole), load_image_array(strips))


def test_formats_and_bit_depths(session: Any) -> None:
    (jpeg,) = run(session, "a.png", kind="relit", format="jpeg", bit_depth=16, quality=95)
    assert jpeg.suffix == ".jpg" and load_image_array(jpeg).dtype == np.uint8  # JPEG is 8-bit
    (tiff,) = run(session, "b", kind="relit", format="tiff", bit_depth=16)
    assert tiff.suffix == ".tif" and load_image_array(tiff).dtype == np.uint16
    # A JPEG layer's transparent version still needs alpha, so it is a PNG.
    _layer, alpha = run(session, "c.jpg", kind="light_layer", format="jpeg", alpha=True)
    assert alpha.name == "c_alpha.png"


def test_derived_files_never_overwrite(session: Any, tmp_path: Path) -> None:
    out = session[3]
    (out / "lights_1_Key.png").write_bytes(b"mine")
    first, _second = run(session, "lights.png", kind="per_light")
    assert first.name == "lights_1_Key (2).png"
    assert (out / "lights_1_Key.png").read_bytes() == b"mine"
    assert unique_path(tmp_path / "new.png") == tmp_path / "new.png"


def test_bad_options_are_rejected() -> None:
    with pytest.raises(ValueError):
        ExportOptions(kind="everything")
    with pytest.raises(ValueError):
        ExportOptions(bit_depth=12)
