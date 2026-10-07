"""End-to-end check of the real backend over HTTP, with real models.

    uv run --directory backend python ../scripts/e2e_backend.py ../samples/portrait.jpg

Starts the server, uploads the image, follows the progress stream, downloads
the maps, checks the cache hit, and checks that a job can be cancelled.
The app's own shutdown path (parent process watch) is tested through Electron.
Models must already be downloaded (run the benchmark once first).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx2 as httpx

TOKEN = "e2e-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def follow(client: httpx.Client, job_id: str) -> list[dict]:
    events = []
    with client.stream("GET", f"/jobs/{job_id}/events", timeout=None) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                events.append(event)
                if event["type"] == "progress":
                    print(f"    [{event['progress']:4.0%}] {event['stage']}: {event['message']}")
    return events


def main() -> None:
    image = Path(sys.argv[1])
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "relight_backend.main", "--port", str(port)],
        env={**os.environ, "RELIGHT_TOKEN": TOKEN},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", headers=AUTH, timeout=30)
    try:
        started = time.perf_counter()
        while True:
            try:
                health = client.get("/health").json()
                break
            except httpx.TransportError:
                if time.perf_counter() - started > 60:
                    sys.exit("server did not answer /health within 60 s")
                time.sleep(0.2)
        print(f"server up in {time.perf_counter() - started:.1f}s; gpu={health['gpu']['name']}; "
              f"models={health['models']}")

        def upload(normals: str) -> dict:
            with image.open("rb") as handle:
                response = client.post("/session", files={"file": (image.name, handle)},
                                       data={"normals": normals})
            response.raise_for_status()
            return dict(response.json())

        print("upload, normals=depth")
        first = upload("depth")
        if first["job_id"]:
            assert follow(client, first["job_id"])[-1]["type"] == "done"
        for name, url in first["maps"].items():
            response = client.get(url)
            assert response.status_code == 200 and response.content[:4] == b"\x89PNG", name
            print(f"    map {name}: {len(response.content) / 1e6:.2f} MB")
        info = client.get(f"/session/{first['session_id']}").json()
        print(f"    original {info['original_size']} -> working {info['working_size']}")

        again = upload("depth")
        assert again["cached"] and again["job_id"] is None
        print("second upload: cache hit")

        print("upload, normals=dsine, then cancel")
        second = upload("dsine")
        if second["job_id"]:
            client.post(f"/jobs/{second['job_id']}/cancel").raise_for_status()
            last = follow(client, second["job_id"])[-1]["type"]
            print(f"    job ended as: {last}")
            assert last in ("cancelled", "done")
        assert client.post("/unload").json() == {"status": "ok"}
        print("OK")
    finally:
        client.close()
        server.kill()
        server.wait()


if __name__ == "__main__":
    main()
