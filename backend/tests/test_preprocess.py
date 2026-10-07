"""Preprocess orchestration, with tiny fake models in place of the real ones."""

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import torch
from PIL import Image

from relight_backend.models import specs
from relight_backend.models.base import Model
from relight_backend.pipeline import preprocess as pp
from relight_backend.pipeline.sessions import SessionStore
from relight_backend.utils import downloads
from relight_backend.utils.image_io import FloatArray, load_gray16, load_normals


class Recorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def report(self, stage: str, progress: float, message: str = "", **extra: Any) -> None:
        self.messages.append(message)

    def check_cancel(self) -> None:
        return None


class FakeModel(Model):
    """Returns a left-to-right ramp (or flat normals), and counts its runs."""

    runs: list[str] = []
    fail_on_gpu = False

    def load(self, weights: Path, code: Path | None, device: torch.device,
             dtype: torch.dtype) -> None:
        if self.fail_on_gpu and device.type == "cuda":
            raise torch.OutOfMemoryError("fake: out of VRAM")
        self._model = object()

    def infer(self, image: Image.Image) -> FloatArray:
        FakeModel.runs.append(self.spec.key)
        ramp = np.tile(np.linspace(0, 1, image.width, dtype=np.float32), (image.height, 1))
        if self.spec is specs.DSINE:
            return np.dstack([ramp * 0, ramp * 0, ramp * 0 + 1]).astype(np.float32)
        return ramp


def fake_class(spec: specs.ModelSpec) -> type[Model]:
    return type(f"Fake_{spec.key}", (FakeModel,), {"spec": spec})


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SessionStore, str]:
    FakeModel.runs = []
    FakeModel.fail_on_gpu = False
    monkeypatch.setattr(pp, "model_class", fake_class)
    monkeypatch.setattr(
        downloads, "ensure", lambda spec, progress, cancel: downloads.ModelFiles(tmp_path, None)
    )
    buffer = io.BytesIO()
    Image.new("RGB", (400, 200), (90, 120, 150)).save(buffer, format="PNG")
    store = SessionStore(tmp_path / "sessions")
    return store, store.create(buffer.getvalue())


def test_writes_all_maps_at_working_size(session: tuple[SessionStore, str]) -> None:
    store, session_id = session
    meta = pp.preprocess(store, session_id, "a.png", pp.PreprocessOptions("dsine", 100), Recorder())

    assert meta.original_size == (400, 200) and meta.working_size == (100, 50)
    for name in ("albedo_proxy", "normal", "depth", "mask"):
        path = store.map_path(session_id, name)
        assert path is not None and Image.open(path).size == (100, 50), name
    assert set(meta.stats) == {"mask", "depth", "normals_dsine"}
    assert load_gray16(store.map_path(session_id, "depth")).max() > 0.99  # type: ignore[arg-type]


def test_second_run_reuses_maps_and_only_adds_new_normals(
    session: tuple[SessionStore, str],
) -> None:
    store, session_id = session
    pp.preprocess(store, session_id, "a.png", pp.PreprocessOptions("dsine", 100), Recorder())
    assert FakeModel.runs == ["birefnet_lite", "depth_anything_v2_small", "dsine"]

    meta = pp.preprocess(store, session_id, "a.png", pp.PreprocessOptions("depth", 100), Recorder())
    assert FakeModel.runs == ["birefnet_lite", "depth_anything_v2_small", "dsine"]  # no reruns
    assert meta.normals_method == "depth"
    assert set(meta.stats) == {"mask", "depth", "normals_dsine", "normals_depth"}

    # The ramp depth is nearer on the right, so depth-derived normals lean left.
    normals = load_normals(store.map_path(session_id, "normal"))  # type: ignore[arg-type]
    assert normals[25, 50, 0] < -0.05


def test_changing_working_size_recomputes(session: tuple[SessionStore, str]) -> None:
    store, session_id = session
    pp.preprocess(store, session_id, "a.png", pp.PreprocessOptions("dsine", 100), Recorder())
    meta = pp.preprocess(store, session_id, "a.png", pp.PreprocessOptions("dsine", 200), Recorder())
    assert meta.working_size == (200, 100)
    assert len(FakeModel.runs) == 6


def test_gpu_out_of_memory_falls_back_to_cpu(
    session: tuple[SessionStore, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, session_id = session
    FakeModel.fail_on_gpu = True
    monkeypatch.setattr(pp, "pick_device", lambda: torch.device("cuda"))
    recorder = Recorder()

    meta = pp.preprocess(store, session_id, "a.png", pp.PreprocessOptions("dsine", 100), recorder)

    assert meta.stats["mask"]["device"] == "cpu"
    assert any("out of memory" in message for message in recorder.messages)
