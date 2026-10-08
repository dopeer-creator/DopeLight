"""Photoreal pass: everything around the diffusion model (which is replaced by a stub)."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from test_export import LIGHTS, Quiet, make_session

from relight_backend.jobs import JobCancelled
from relight_backend.pipeline import photoreal
from relight_backend.pipeline.export import ExportOptions, export_photoreal
from relight_backend.pipeline.photoreal import (
    RenderOptions,
    apply_ratio,
    guided_filter,
    lighting_ratio,
    make_hint,
    render,
)
from relight_backend.pipeline.sessions import map_file
from relight_backend.pipeline.shading import GlobalSettings
from relight_backend.utils import downloads
from relight_backend.utils.image_io import load_image_array


class FakeIcLight:
    """Stands in for the diffusion model: returns the photo, brighter on the left half."""

    out_of_memory_times = 0
    loads: list[bool] = []

    def load(self, base: Path, offsets: Path, device: Any, dtype: Any,
             low_memory: bool = False) -> None:
        FakeIcLight.loads.append(low_memory)

    def unload(self) -> None:
        return None

    def total_steps(self, params: Any) -> int:
        return 4

    def relight(self, picture: Image.Image, hint: Image.Image, params: Any, on_step: Any) -> Any:
        if FakeIcLight.out_of_memory_times > 0:
            FakeIcLight.out_of_memory_times -= 1
            import torch

            raise torch.OutOfMemoryError("fake")
        for _ in range(4):
            on_step()
        pixels = np.asarray(picture, dtype=np.float32)
        pixels[:, : picture.width // 2] *= 1.6
        return Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), mode="RGB")


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    store, session_id, original = make_session(tmp_path / "sessions")
    folder = tmp_path / "sessions" / session_id
    # The app's copy of the photo at working size.
    Image.fromarray(original, mode="RGB").resize((48, 32)).save(
        folder / map_file("albedo_proxy", "depth")
    )
    FakeIcLight.out_of_memory_times, FakeIcLight.loads = 0, []
    monkeypatch.setattr(photoreal, "IcLight", FakeIcLight)
    monkeypatch.setattr(
        downloads, "ensure", lambda spec, progress, cancel: downloads.ModelFiles(tmp_path, None)
    )
    return store, session_id, original, tmp_path


def test_guided_filter_keeps_flat_values_and_edges() -> None:
    guide = np.zeros((40, 60), dtype=np.float32)
    guide[:, 30:] = 1.0  # one hard edge
    noisy = np.dstack([guide * 2.0 + 1.0] * 3).astype(np.float32)
    noisy += np.random.default_rng(0).normal(0, 0.05, noisy.shape).astype(np.float32)
    smooth = guided_filter(guide, noisy, radius=4, epsilon=0.01)
    assert np.abs(smooth[:, :25] - 1.0).max() < 0.06  # noise mostly gone
    assert np.abs(smooth[:, 35:] - 3.0).max() < 0.06
    assert smooth[20, 31, 0] - smooth[20, 28, 0] > 1.5  # the edge is still an edge


def test_ratio_is_one_for_an_unchanged_picture_and_bounded() -> None:
    picture = np.random.default_rng(1).uniform(0.1, 0.9, (32, 48, 3)).astype(np.float32)
    assert np.abs(lighting_ratio(picture, picture) - 1.0).max() < 1e-3
    wild = lighting_ratio(np.full((32, 48, 3), 0.01, dtype=np.float32),
                          np.ones((32, 48, 3), dtype=np.float32))
    assert wild.max() <= photoreal.RATIO_MAX


def test_model_light_is_used_on_the_subject_and_preview_light_elsewhere() -> None:
    original = np.full((40, 80, 3), 0.5, dtype=np.float32)
    model_says = np.full((40, 80, 3), 0.9, dtype=np.float32)  # much brighter everywhere
    preview_says = np.full((40, 80, 3), 0.6, dtype=np.float32)  # a little brighter
    subject = np.zeros((40, 80), dtype=np.float32)
    subject[:, :40] = 1.0  # the left half is the subject
    ratio = lighting_ratio(original, model_says, preview_says, subject)
    lin = photoreal._linear
    eps = photoreal.RATIO_EPSILON
    from_model = (lin(model_says)[0, 0, 0] + eps) / (lin(original)[0, 0, 0] + eps)
    from_preview = (lin(preview_says)[0, 0, 0] + eps) / (lin(original)[0, 0, 0] + eps)
    assert ratio[20, 10, 0] == pytest.approx(from_model, rel=0.02)
    assert ratio[20, 70, 0] == pytest.approx(from_preview, rel=0.02)
    # With no subject to speak of, the model's light is used everywhere.
    everywhere = lighting_ratio(original, model_says, preview_says, np.zeros_like(subject))
    assert everywhere[20, 70, 0] == pytest.approx(from_model, rel=0.02)


def test_colour_changes_are_limited_but_brightness_is_not() -> None:
    blue = np.zeros((40, 60, 3), dtype=np.float32)
    blue[..., 2] = 0.8
    blue[..., :2] = 0.2
    # The model "repaints" it green at the same brightness: mostly a colour change.
    green = blue[..., [0, 2, 1]].copy()
    ratio = lighting_ratio(blue, green)
    relit = photoreal._linear(blue) * ratio
    assert relit[20, 30, 2] > relit[20, 30, 1]  # still more blue than green
    # A plain brightening goes through in full.
    dim = np.full((40, 60, 3), 0.5, dtype=np.float32)
    dim[..., 2] = 0.6
    lit = dim * 1.5
    lin = photoreal._linear
    eps = photoreal.RATIO_EPSILON
    expected = (lin(lit)[0, 0] + eps) / (lin(dim)[0, 0] + eps)
    assert expected.min() > 2.0  # more than twice as bright in linear light
    assert np.allclose(lighting_ratio(dim, lit)[20, 30], expected, rtol=0.03)


def test_model_cannot_brighten_far_past_the_preview() -> None:
    """A black cloth redrawn as a pale one is repainting, not lighting."""
    dark = np.full((40, 60, 3), 0.2, dtype=np.float32)
    repainted = np.full((40, 60, 3), 0.95, dtype=np.float32)  # the model makes it nearly white
    barely_lit = np.full((40, 60, 3), 0.22, dtype=np.float32)  # the preview: hardly any light
    subject = np.ones((40, 60), dtype=np.float32)
    lin, eps = photoreal._linear, photoreal.RATIO_EPSILON
    preview = (lin(barely_lit)[0, 0, 0] + eps) / (lin(dark)[0, 0, 0] + eps)
    ratio = lighting_ratio(dark, repainted, barely_lit, subject)[20, 30, 0]
    assert ratio == pytest.approx(preview * photoreal.BRIGHTNESS_LEASH, rel=0.03)


def test_light_the_model_adds_on_its_own_keeps_the_models_colour() -> None:
    grey = np.full((40, 60, 3), 0.4, dtype=np.float32)
    warm = grey.copy()
    warm[..., 0] = 0.6  # the model adds a warm glow
    warm[..., 2] = 0.3
    subject = np.ones((40, 60), dtype=np.float32)
    # The preview put no light here at all, so there is no light colour to borrow.
    ratio = lighting_ratio(grey, warm, grey, subject)[20, 30]
    assert ratio[0] > 1.2 > 0.9 > ratio[2]  # still warm, not grey


def test_ratio_transfer_keeps_the_originals_detail() -> None:
    rng = np.random.default_rng(2)
    full = rng.uniform(0.2, 0.6, (128, 192, 3)).astype(np.float32)  # fine texture
    ratio = np.full((32, 48, 3), 2.0, dtype=np.float32)  # "twice as bright", low resolution
    relit = apply_ratio(full, ratio)
    assert relit.shape == full.shape
    eps = photoreal.RATIO_EPSILON
    expected = (photoreal._linear(full) + eps) * 2.0 - eps
    assert np.allclose(relit, expected, atol=1e-5)  # texture intact


def test_a_black_background_can_receive_light() -> None:
    black = np.zeros((32, 48, 3), dtype=np.float32)
    glow = np.zeros((32, 48, 3), dtype=np.float32)
    glow[..., 2] = 0.5  # the light paints it blue
    relit = apply_ratio(black, lighting_ratio(black, glow, hint=glow))
    assert relit[16, 24, 2] > 0.15 and relit[16, 24, 0] < 0.01  # blue arrived, red did not


def test_a_coloured_light_comes_through_in_full() -> None:
    grey = np.full((40, 60, 3), 0.5, dtype=np.float32)
    model_says = np.full((40, 60, 3), 0.7, dtype=np.float32)  # brighter, but colourless
    blue_light = grey.copy()
    blue_light[..., 2] = 0.95  # the preview: a strongly blue light
    blue_light[..., 0] = 0.35
    subject = np.ones((40, 60), dtype=np.float32)
    # Original light at 50 %: the blue light supplies most of the brightness there.
    ratio = lighting_ratio(grey, model_says, blue_light, subject, base_level=0.5)[20, 30]
    lin, eps = photoreal._linear, photoreal.RATIO_EPSILON
    # Blue against red is as strong as in the preview: far past the old 1.5x cap.
    wanted = (lin(blue_light)[0, 0, 2] + eps) / (lin(blue_light)[0, 0, 0] + eps)
    assert ratio[2] / ratio[0] == pytest.approx(wanted, rel=0.03) and wanted > 5


def test_adherence_maps_to_less_freedom() -> None:
    loose, tight = RenderOptions(adherence=0.0).params(), RenderOptions(adherence=1.0).params()
    assert loose.denoise == pytest.approx(0.95) and tight.denoise == pytest.approx(0.5)
    assert RenderOptions(steps=12, seed=7, highres=False).params().steps == 12


def test_hint_is_the_preview_shading_at_the_diffusion_size(session: Any) -> None:
    store, session_id, _original, tmp_path = session
    folder = tmp_path / "sessions" / session_id
    photo, hint = make_hint(folder, "depth", (128, 64), LIGHTS, GlobalSettings())
    assert photo.size == hint.size == (128, 64)
    assert np.asarray(hint, dtype=int).mean() > np.asarray(photo, dtype=int).mean() + 5  # lit


def test_render_writes_ratio_and_preview(session: Any) -> None:
    store, session_id, original, tmp_path = session
    result = render(store, session_id, LIGHTS, GlobalSettings(),
                    RenderOptions(long_edge=128, highres=False), Quiet())
    folder = photoreal.render_folder(store, session_id, result["render_id"])
    assert folder is not None and result["diffusion_size"] == [128, 64]

    ratio = np.load(folder / photoreal.RATIO_FILE)
    assert ratio.shape == (64, 128, 3)
    assert ratio[:, :40].mean() > 2.0 and abs(ratio[:, 90:].mean() - 1.0) < 0.05

    preview = np.asarray(Image.open(folder / photoreal.PREVIEW_FILE), dtype=int)
    assert preview.shape[:2] == original.shape[:2]  # small photo: shown at its own size
    assert (preview[:, :30] - original[:, :30]).mean() > 15  # left half got brighter
    assert photoreal.render_folder(store, session_id, "nope") is None
    assert photoreal.render_folder(store, session_id, "../x") is None


def test_render_retries_smaller_when_the_gpu_runs_out(
    session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import torch

    store, session_id, _original, _tmp = session
    FakeIcLight.out_of_memory_times = 1
    monkeypatch.setattr(photoreal, "pick_device", lambda: torch.device("cuda"))
    monkeypatch.setattr(photoreal, "pick_dtype", lambda device: torch.float32)
    result = render(store, session_id, LIGHTS, GlobalSettings(),
                    RenderOptions(long_edge=320, highres=False), Quiet())
    assert result["diffusion_size"] == [256, 192]  # 0.8 x 320, rounded to 64s
    assert FakeIcLight.loads == [False, True] and "smaller" in result["note"]


def test_render_can_be_cancelled(session: Any) -> None:
    store, session_id, _original, _tmp = session

    class CancelAtOnce(Quiet):
        def check_cancel(self) -> None:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        render(store, session_id, LIGHTS, GlobalSettings(), RenderOptions(), CancelAtOnce())


def test_photoreal_exports(session: Any) -> None:
    store, session_id, original, tmp_path = session
    rid = render(store, session_id, LIGHTS, GlobalSettings(),
                 RenderOptions(long_edge=128, highres=False), Quiet())["render_id"]
    out = tmp_path / "out"
    out.mkdir()

    def run(name: str, **options: Any) -> list[Path]:
        chosen = ExportOptions(**options)
        return export_photoreal(store, session_id, rid, chosen, out / name, Quiet())

    (relit_path,) = run("relit.png", kind="relit", bit_depth=16)
    (layer_path,) = run("light.png", kind="light_layer", bit_depth=16)
    (multiply_path,) = run("multiply.png", kind="multiply", bit_depth=16)
    relit, layer = load_image_array(relit_path), load_image_array(layer_path)
    assert relit.shape == original.shape and relit.dtype == np.uint16

    # Add blend: original + light layer = relit, wherever the render made things brighter
    # (a layer that adds cannot darken, so darker pixels are left as the original).
    original16, relit16 = original.astype(np.int64) * 257, relit.astype(np.int64)
    rebuilt = original16 + layer.astype(np.int64)
    brighter = relit16 >= original16
    # Coloured lights lower some channels while raising others, so not every value is brighter.
    assert brighter.mean() > 0.6
    assert np.abs(rebuilt - relit16)[brighter].max() <= 3
    assert (layer[~brighter] == 0).all()

    # Multiply layer: 0.5 means no change; the left half was brightened 1.6x in sRGB values.
    multiply = load_image_array(multiply_path) / 65535.0
    assert abs(multiply[:, 70:].mean() - 0.5) < 0.1 and multiply[:, :30].mean() > 0.9

    with pytest.raises(ValueError):
        run("x.png", kind="per_light")
    with pytest.raises(KeyError):
        export_photoreal(store, session_id, "missing", ExportOptions(), out / "y.png", Quiet())
