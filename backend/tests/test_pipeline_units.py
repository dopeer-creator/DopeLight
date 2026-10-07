"""Fast tests for the parts of the pipeline that need no model weights."""

from pathlib import Path

import numpy as np
import pytest

from relight_backend.jobs import JobManager
from relight_backend.models import specs
from relight_backend.pipeline.normals_from_depth import normals_from_depth
from relight_backend.pipeline.sessions import SessionMeta, SessionStore, map_file
from relight_backend.utils import downloads
from relight_backend.utils.image_io import (
    load_gray16,
    load_normals,
    save_gray16,
    save_normals,
)


def ramp(width: int = 96, height: int = 64, axis: str = "x") -> np.ndarray:
    """Depth that rises toward the right (axis x) or toward the bottom (axis y)."""
    xs, ys = np.meshgrid(np.linspace(0, 1, width), np.linspace(0, 1, height))
    return (xs if axis == "x" else ys).astype(np.float32)


def center(normals: np.ndarray) -> np.ndarray:
    return normals[normals.shape[0] // 2, normals.shape[1] // 2]


def test_flat_depth_gives_normals_facing_viewer() -> None:
    normals = normals_from_depth(np.full((32, 48), 0.5, dtype=np.float32))
    assert np.allclose(normals, [0.0, 0.0, 1.0], atol=1e-4)


def test_depth_rising_to_the_right_tilts_normal_left() -> None:
    # Nearer on the right means the surface faces left: negative X.
    x, y, z = center(normals_from_depth(ramp(axis="x")))
    assert x < -0.1 and abs(y) < 1e-3 and z > 0


def test_depth_rising_downward_tilts_normal_up() -> None:
    # Nearer at the bottom means the surface faces up: positive Y.
    x, y, z = center(normals_from_depth(ramp(axis="y")))
    assert y > 0.1 and abs(x) < 1e-3 and z > 0


def test_normals_are_unit_length() -> None:
    normals = normals_from_depth(ramp(axis="x") * ramp(axis="y"))
    assert np.allclose(np.linalg.norm(normals, axis=-1), 1.0, atol=1e-4)


def test_normal_png_round_trip(tmp_path: Path) -> None:
    normals = normals_from_depth(ramp(axis="x"))
    save_normals(normals, tmp_path / "n.png")
    assert np.abs(load_normals(tmp_path / "n.png") - normals).max() < 0.02  # 8-bit steps


def test_depth_png_round_trip_is_16_bit(tmp_path: Path) -> None:
    depth = ramp()
    save_gray16(depth, tmp_path / "d.png")
    assert np.abs(load_gray16(tmp_path / "d.png") - depth).max() < 1e-4


def test_session_ids_come_from_content_and_are_validated(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    first = store.create(b"image bytes")
    assert store.create(b"image bytes") == first
    assert store.create(b"other bytes") != first
    assert store.folder(first) == tmp_path / first
    assert store.folder("../" + first) is None
    assert store.folder("not-a-session") is None


def test_map_path_needs_finished_session(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    session_id = store.create(b"x")
    assert store.map_path(session_id, "depth") is None  # no meta yet

    store.save_meta(SessionMeta(session_id, "x.png", (4, 4), (4, 4), "dsine", "birefnet_lite"))
    assert store.map_path(session_id, "normal") is None  # file missing
    (tmp_path / session_id / map_file("normal", "dsine")).write_bytes(b"png")
    assert store.map_path(session_id, "normal") == tmp_path / session_id / "normal_dsine.png"
    assert store.map_path(session_id, "secrets") is None


def test_job_reports_progress_then_result() -> None:
    def work(job):  # type: ignore[no-untyped-def]
        job.report("stage", 0.5, "half")
        return {"answer": 42}

    job = JobManager().submit("test", work)
    events = [e for e in job.stream(poll_seconds=5) if e["type"] != "keepalive"]
    assert [e["type"] for e in events] == ["progress", "done"]
    assert events[-1]["result"] == {"answer": 42}
    assert job.state == "done"


def test_job_cancel_and_error() -> None:
    manager = JobManager()

    def waits_for_cancel(job):  # type: ignore[no-untyped-def]
        job.report("stage", 0.0)
        while True:
            job.check_cancel()

    cancelled = manager.submit("test", waits_for_cancel)
    stream = cancelled.stream(poll_seconds=5)
    assert next(stream)["type"] == "progress"
    cancelled.cancel()
    assert [e["type"] for e in stream][-1] == "cancelled"

    def fails(job):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    failed = manager.submit("test", fails)
    last = list(failed.stream(poll_seconds=5))[-1]
    assert last["type"] == "error" and "boom" in last["error"]


def test_model_not_ready_without_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELIGHT_DATA_DIR", str(tmp_path))
    assert not any(downloads.is_ready(spec) for spec in specs.ALL)
    assert downloads.code_path(specs.DSINE.code).name == "DSINE-hub-a6b7d253d515"  # type: ignore[arg-type]


def test_specs_are_pinned_and_consistent() -> None:
    for spec in specs.ALL:
        assert len(spec.weights.revision) == 40, spec.key
        assert spec.code is None or len(spec.code.commit) == 40
    assert specs.DEFAULT_NORMALS in specs.NORMALS
    assert specs.specs_for("depth") == [specs.MASK, specs.DEPTH]
    assert specs.DSINE in specs.specs_for("dsine")
    assert not specs.DSINE.commercial_use
