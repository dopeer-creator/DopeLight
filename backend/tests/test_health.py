from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relight_backend.constants import APP_NAME
from relight_backend.main import create_app
from relight_backend.utils.vram import parse_nvidia_smi

TOKEN = "test-token"


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELIGHT_DATA_DIR", str(tmp_path))


def client() -> TestClient:
    return TestClient(create_app(TOKEN))


def test_health_requires_token() -> None:
    assert client().get("/health").status_code == 401


def test_health_rejects_wrong_token() -> None:
    response = client().get("/health", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_health_ok_with_token() -> None:
    response = client().get("/health", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == APP_NAME
    assert set(body["gpu"]) == {"available", "name", "vram_total_mb", "vram_free_mb", "source"}
    assert isinstance(body["models"], dict)


def test_parse_nvidia_smi() -> None:
    info = parse_nvidia_smi("NVIDIA GeForce RTX 4050 Laptop GPU, 6141, 5890\n")
    assert info is not None
    assert info.name == "NVIDIA GeForce RTX 4050 Laptop GPU"
    assert info.vram_total_mb == 6141
    assert info.vram_free_mb == 5890
    assert info.source == "nvidia-smi"


def test_parse_nvidia_smi_garbage() -> None:
    assert parse_nvidia_smi("") is None
    assert parse_nvidia_smi("not, csv") is None
    assert parse_nvidia_smi("name, x, y") is None
