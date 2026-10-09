"""Endpoint tests. The model pipeline is replaced by a stub that writes tiny maps."""

import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from relight_backend.main import create_app
from relight_backend.pipeline import preprocess as preprocess_module
from relight_backend.pipeline.sessions import MAP_NAMES, SessionMeta, SessionStore, map_file
from relight_backend.utils.image_io import save_gray8, save_gray16

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def png_bytes(color: tuple[int, int, int] = (200, 120, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(buffer, format="PNG")
    return buffer.getvalue()


def fake_preprocess(store: SessionStore, session_id: str, source_name: str, options: Any,
                    reporter: Any) -> SessionMeta:
    reporter.report("mask", 0.5, "stub")
    folder = store.folder(session_id)
    assert folder is not None
    for name in MAP_NAMES:
        (folder / map_file(name, options.normals)).write_bytes(png_bytes())
    meta = SessionMeta(session_id, source_name, (8, 6), (8, 6), options.normals, "stub")
    store.save_meta(meta)
    return meta


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RELIGHT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(preprocess_module, "preprocess", fake_preprocess)
    return TestClient(create_app(TOKEN, data_root=tmp_path / "sessions"))


def events(client: TestClient, job_id: str) -> list[dict[str, Any]]:
    body = client.get(f"/jobs/{job_id}/events", headers=AUTH).text
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def upload(client: TestClient, data: bytes, **form: str) -> Any:
    return client.post("/session", headers=AUTH, files={"file": ("photo.png", data)}, data=form)


def test_every_endpoint_requires_token(client: TestClient) -> None:
    assert client.post("/session", files={"file": ("a.png", png_bytes())}).status_code == 401
    assert client.get("/session/abc/depth").status_code == 401
    assert client.post("/models/ensure", json={}).status_code == 401
    assert client.post("/unload").status_code == 401
    assert client.get("/jobs/abc").status_code == 401


def test_health_lists_models(client: TestClient) -> None:
    models = client.get("/health", headers=AUTH).json()["models"]
    assert set(models) == {"birefnet_lite", "depth_anything_v2_small", "dsine",
                           "stablenormal_turbo", "sd15_realistic_vision", "ic_light_fc"}
    assert not any(models.values())  # nothing downloaded in the temp data folder


def test_session_flow_then_cache_hit(client: TestClient) -> None:
    first = upload(client, png_bytes(), normals="depth").json()
    assert first["cached"] is False and first["job_id"]
    assert set(first["maps"]) == set(MAP_NAMES)

    kinds = [event["type"] for event in events(client, first["job_id"])]
    assert kinds[0] == "progress" and kinds[-1] == "done"
    assert client.get(f"/jobs/{first['job_id']}", headers=AUTH).json()["state"] == "done"

    for url in first["maps"].values():
        response = client.get(url, headers=AUTH)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    info = client.get(f"/session/{first['session_id']}", headers=AUTH).json()
    assert info["normals_method"] == "depth" and info["source_name"] == "photo.png"

    again = upload(client, png_bytes(), normals="depth").json()
    assert again["cached"] is True and again["job_id"] is None
    assert again["session_id"] == first["session_id"]


def test_depth_raw_serves_16_bit_values(client: TestClient, tmp_path: Path) -> None:
    first = upload(client, png_bytes(), normals="depth").json()
    events(client, first["job_id"])
    depth = np.linspace(0, 1, 48, dtype=np.float32).reshape(6, 8)
    save_gray16(depth, tmp_path / "sessions" / first["session_id"] / "depth.png")

    response = client.get(f"/session/{first['session_id']}/depth_raw", headers=AUTH)
    assert response.status_code == 200
    values = np.frombuffer(response.content, dtype="<u2").reshape(6, 8)
    assert values[0, 0] == 0 and values[-1, -1] == 65535
    assert np.abs(values / 65535.0 - depth).max() < 1e-4
    assert client.get("/session/0123456789abcdef0123/depth_raw", headers=AUTH).status_code == 404


def test_thickness_raw_serves_one_byte_per_pixel(client: TestClient, tmp_path: Path) -> None:
    first = upload(client, png_bytes(), normals="depth").json()
    events(client, first["job_id"])
    folder = tmp_path / "sessions" / first["session_id"]
    assert (folder / "thickness.png").exists()  # preprocess writes it
    code = np.linspace(0, 1, 48, dtype=np.float32).reshape(6, 8)
    save_gray8(code, folder / "thickness.png")

    response = client.get(f"/session/{first['session_id']}/thickness_raw", headers=AUTH)
    assert response.status_code == 200
    values = np.frombuffer(response.content, dtype=np.uint8).reshape(6, 8)
    assert values[0, 0] == 0 and values[-1, -1] == 255
    assert np.abs(values / 255.0 - code).max() < 3e-3
    missing = client.get("/session/0123456789abcdef0123/thickness_raw", headers=AUTH)
    assert missing.status_code == 404


def test_export_writes_files_and_reports_them(tmp_path: Path) -> None:
    from test_export import make_session

    _store, session_id, _original = make_session(tmp_path / "sessions")
    api = TestClient(create_app(TOKEN, data_root=tmp_path / "sessions"))
    light = {
        "id": "a", "name": "Key", "enabled": True, "type": "point",
        "position": {"x": 0.3, "y": 0.3, "z": 0.7}, "target": {"x": 0.5, "y": 0.5},
        "color": [1, 0.8, 0.6], "intensity": 0.8, "diffusion": 0.3, "radius": 0.8,
        "specular": 0.2, "shininess": 32, "coneAngle": 50, "coneSoftness": 0.5,
        "castShadows": False, "shadowStrength": 0.7,
    }
    body = {
        "lights": [light], "globals": {"ambient": 0, "exposure": 0, "keepOriginalLight": 1},
        "kind": "light_layer", "alpha": True, "target": str(tmp_path / "photo_light.png"),
    }
    started = api.post(f"/session/{session_id}/export", headers=AUTH, json=body)
    assert started.status_code == 200
    last = events(api, started.json()["job_id"])[-1]
    assert last["type"] == "done", last
    files = [Path(name) for name in last["result"]["files"]]
    assert [path.name for path in files] == ["photo_light.png", "photo_light_alpha.png"]
    assert all(path.stat().st_size > 100 for path in files)

    body["target"] = str(tmp_path / "missing folder" / "x.png")
    assert api.post(f"/session/{session_id}/export", headers=AUTH, json=body).status_code == 400
    body["target"] = "relative.png"
    assert api.post(f"/session/{session_id}/export", headers=AUTH, json=body).status_code == 400
    unknown = "/session/0123456789abcdef0123/export"
    assert api.post(unknown, headers=AUTH, json=body).status_code == 404


def test_other_normals_method_is_not_a_cache_hit(client: TestClient) -> None:
    first = upload(client, png_bytes(), normals="depth").json()
    events(client, first["job_id"])
    assert upload(client, png_bytes(), normals="dsine").json()["cached"] is False


def test_bad_uploads_are_rejected(client: TestClient) -> None:
    assert upload(client, b"this is not an image").status_code == 400
    assert upload(client, png_bytes(), normals="magic").status_code == 400


def test_unknown_things_are_404(client: TestClient) -> None:
    assert client.get("/session/0123456789abcdef0123/depth", headers=AUTH).status_code == 404
    assert client.get("/session/0123456789abcdef0123", headers=AUTH).status_code == 404
    assert client.get("/jobs/nope", headers=AUTH).status_code == 404
    assert client.post("/jobs/nope/cancel", headers=AUTH).status_code == 404


def test_ensure_rejects_unknown_model(client: TestClient) -> None:
    response = client.post("/models/ensure", headers=AUTH, json={"models": ["nope"]})
    assert response.status_code == 400


def test_unload_ok(client: TestClient) -> None:
    assert client.post("/unload", headers=AUTH).json() == {"status": "ok"}
