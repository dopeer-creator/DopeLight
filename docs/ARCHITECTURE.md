# Architecture

## Processes

```
Electron main  ──spawns──▶  Python backend (FastAPI, 127.0.0.1:<free port>)
     │  IPC (backend:get / backend:changed)        ▲
     ▼                                              │ HTTP + Bearer token
Electron renderer (React) ──────────────────────────┘
```

- **Main** (`app/src/main`): creates the window, owns the backend child process, and tells the renderer the backend's URL and token over IPC.
- **Preload** (`app/src/preload`): exposes a small typed API on `window.relight`. The renderer is sandboxed with context isolation; it has no Node access.
- **Renderer** (`app/src/renderer`): React UI. Talks to the backend directly over HTTP with the token.
- **Backend** (`backend/relight_backend`): FastAPI app with model wrappers (`models/`), the processing pipeline (`pipeline/`), and helpers (`utils/`).

## Backend lifecycle

1. Main finds a free port and generates a random token for this launch.
2. Main spawns the venv Python with `--port` and `--parent-pid <Electron's process id>`; the token is passed in the `RELIGHT_TOKEN` environment variable.
3. Main polls `GET /health` until it answers (30 s limit), then reports state `running`.
4. On quit, main kills the backend's process tree.
5. The backend also waits on the parent's process handle. If Electron dies without running its quit handlers, the backend notices and shuts itself down. This is what prevents orphan Python processes.

Backend states sent to the renderer: `starting`, `running`, `stopped`, `error` (with a message).

The server imports PyTorch and the model libraries only inside jobs, so it answers `/health` about a second after starting (the first `/health` also probes the GPU, a few seconds).

## Endpoints

All require `Authorization: Bearer <token>`.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | status, app version, GPU name and VRAM, which models are downloaded |
| `POST /models/ensure` | body `{"models": [...]}` (omit for all); downloads missing models; returns `job_id` |
| `POST /session` | multipart `file` plus optional form field `normals` (`dsine`, `stablenormal`, `depth`); stores the image and starts preprocess; returns `session_id`, `job_id`, map URLs. If the maps are already cached: `cached: true`, no job |
| `GET /session/{id}` | sizes, normals method, and per-model time/VRAM stats of a finished session |
| `GET /session/{id}/{map}` | PNG; map is `albedo_proxy`, `normal`, `depth`, or `mask` |
| `GET /jobs/{id}` | job state, result, or error |
| `GET /jobs/{id}/events` | server-sent events: every progress event so far, then live ones until the job ends |
| `POST /jobs/{id}/cancel` | cancel; takes effect at the next stage boundary, or immediately during a download |
| `POST /unload` | free VRAM |

Jobs run one at a time on a single worker thread, so two models never compete for VRAM. Progress events look like `{"type": "progress", "stage": "depth", "progress": 0.35, "message": "Running Depth Anything V2 Small"}`; during downloads they also carry `download_done_mb` and `download_total_mb`. The last event is `done`, `error`, or `cancelled`.

## Preprocess

Runs once per image (`pipeline/preprocess.py`). The original file is stored untouched; maps are computed at the **working size** (long edge at most 1536 px).

1. **Mask** — BiRefNet lite, 1024×1024 input.
2. **Depth** — Depth Anything V2 Small.
3. **Normals** — DSINE by default; StableNormal turbo or depth-derived by setting.
4. **Albedo proxy** — the image itself at working size (v1: no intrinsic decomposition). The optional shading-flattening step from the brief is not built.

Each model is downloaded if missing, loaded, run, and unloaded before the next, so only one is in VRAM at a time. On the GPU, models run in half precision (DSINE stays in full precision, as its authors' code does). If a model runs out of VRAM it is retried on the CPU and the session stats record that.

### Map conventions

| Map | File | Encoding |
| --- | --- | --- |
| albedo proxy | `albedo_proxy.png` | 8-bit sRGB; the shader converts to linear |
| mask | `mask.png` | 8-bit gray; white = subject |
| depth | `depth.png` | **16-bit** gray; **white (1.0) = nearest**. Relative, not metric: scaled per image between the 0.5th and 99.5th percentile |
| normals | `normal_<method>.png` | 8-bit RGB, `rgb = (n × 0.5 + 0.5) × 255`. **Camera space: +X right, +Y up, +Z toward the viewer** (a surface facing the camera is `(128, 128, 255)`) |

Depth becomes scene depth in image-width units through `DEPTH_SCALE` (0.4) in `constants.py`: `z = DEPTH_SCALE × depth`. The live-preview shader (Phase 2) must use the same value.

DSINE and StableNormal both output X pointing left; the wrappers flip X. This was measured, not assumed: the benchmark correlates each model's normals with depth-derived ones per axis.

### Session cache

`<data>/sessions/<id>/`, where the id is the first 20 hex digits of the image's SHA-256. Opening the same image again returns the cached maps at once. Normals are stored per method, so switching method keeps mask, depth, and the other normals.

### Model downloads

`utils/downloads.py` plus `utils/fetch_weights.py`:

- Weights come from Hugging Face into `<data>/models/hf`, pinned to exact revisions. The download runs in a **separate process**, so cancelling just kills it; partial files resume next time. Sizes are verified by the Hugging Face client.
- DSINE and StableNormal also need a few source files from GitHub. Only the listed files are fetched, at a pinned commit, into `<data>/models/code`.
- A marker file in `<data>/models/ready` records a complete model; that is what `/health` reports, and it works offline.
- The server process itself runs with `HF_HUB_OFFLINE=1` and telemetry off. Only the fetch process touches the network.

## GPU detection

`utils/vram.py` tries, in order: PyTorch CUDA, the `nvidia-smi` program, then reports no GPU.

## Logs

JSON lines in `<data>/logs/`: `main.log` (Electron main and renderer warnings/errors) and `backend.log` (Python, rotating).

## Normals: comparison and recommendation

Benchmark: `npm run bench` on four photos (portrait, product, interior, landscape) at working size 1536 px. Run twice: on the target PC's GPU (2026-10-07) and on the build laptop's CPU (2026-10-03).

### GPU: RTX 4050 Laptop, 6 GB (target PC)

PyTorch 2.14.1+cu126, half precision (DSINE full precision). All stages ran on the GPU; none fell back to the CPU. 5080 MB of 6140 MB was free when the run started.

Seconds per image (inference; load time in brackets) and peak VRAM:

| Step | Model | Interior (first image) | Landscape | Portrait | Product | Peak VRAM, highest of the four |
| --- | --- | --- | --- | --- | --- | --- |
| mask | BiRefNet lite | 0.95 (11.8) | 0.19 (0.7) | 0.35 (0.7) | 0.30 (0.7) | 850 MB |
| depth | Depth Anything V2 Small | 0.36 (0.8) | 0.09 (0.5) | 0.08 (0.5) | 0.08 (0.5) | 214 MB |
| normals | DSINE | 0.66 (1.3) | 0.59 (1.4) | 0.72 (1.4) | 0.50 (1.3) | 1265 MB |
| normals | StableNormal turbo | 0.79 (9.9) | 0.93 (6.4) | 1.05 (6.1) | 0.94 (5.9) | 4326 MB |
| normals | depth-derived | 0.07 | 0.07 | 0.08 | 0.08 | none (CPU) |

- Every model is under the 5.5 GB limit. StableNormal turbo is the only one that comes close: 4.0 to 4.3 GB depending on image shape (portrait is highest).
- Peak VRAM is PyTorch's `max_memory_allocated`. It leaves out the CUDA context and allocator cache, so the figure `nvidia-smi` shows is a few hundred MB higher.
- A full preprocess with the default (DSINE) takes about 3.5 s per image including model loads, against 45 to 50 s on the laptop CPU. The first image after a start takes about 16 s, nearly all of it the first model load.
- The half-precision sheets match the CPU descriptions in the table further down: DSINE sharpest on the portrait and product, StableNormal softer with red noise patches on the landscape, depth-derived flat with ridges at outlines. No black or broken maps. The CPU sheets were not on this PC, so this is a comparison against the written notes, not a pixel diff.
- Axis check was positive on x, y, and z for both models on all four photos. The weakest value is DSINE z on the product photo (0.04).

### CPU: build laptop

**These numbers are from the build laptop: CPU only (Intel i5-1145G7, 4 cores), full precision, with memory pressure during StableNormal.**

Seconds per image on CPU (inference; load time in brackets):

| Step | Model | Interior | Landscape | Portrait | Product | Download |
| --- | --- | --- | --- | --- | --- | --- |
| mask | BiRefNet lite | 21.4 (3.2) | 26.3 (0.9) | 26.4 (0.9) | 25.1 (0.5) | 170 MB |
| depth | Depth Anything V2 Small | 2.3 (1.6) | 2.0 (0.5) | 1.6 (0.6) | 1.3 (0.7) | 95 MB |
| normals | DSINE | 13.6 (1.5) | 16.6 (1.6) | 19.3 (1.7) | 15.1 (1.3) | 280 MB |
| normals | StableNormal turbo | 37.6 (10.6) | 49.3 (18.3) | 56.6 (16.8) | 44.7 (5.9) | 3.2 GB |
| normals | depth-derived | 0.09 | 0.09 | 0.11 | 0.11 | none |

A full preprocess with the default (DSINE) takes about 45 to 50 s per image on this CPU; the mask is the slowest step.

What the side-by-side sheets show:

| | DSINE | StableNormal turbo | Depth-derived |
| --- | --- | --- | --- |
| Portrait | sharpest: eyes, mouth, collar, pocket flaps all resolved | correct shape but soft; small features blurred | face nearly flat; bright ridges along every outline |
| Product | crisp knobs, reels, and edges; one invented soft blob in a pure-black area | softer, panel detail smeared | usable shapes, ridge artifacts at edges |
| Interior | clean flat walls, ceiling, floor; good furniture | about equal to DSINE | walls and ceiling barely told apart |
| Landscape | smooth, plausible | red noise patches on water, trees, and sky | almost entirely flat |
| Licence | **non-commercial** | Apache-2.0 | none needed |

Axis check (correlation with depth-derived normals) was positive on x, y, and z for both models on all four photos, so the convention in "Map conventions" holds.

**Recommendation: DSINE is the default** (`DEFAULT_NORMALS` in `models/specs.py`). It had the best detail on three of four photos, tied on the fourth, runs about three times faster than StableNormal, and is a tenth of the download. Its one drawback is the non-commercial licence, which is acceptable for personal use (see `docs/LICENSES.md`).

**StableNormal turbo stays as a setting**: the choice if a commercially usable normals model is ever needed. Caveats: it peaks at 4.3 GB of VRAM, so it needs most of the card free. It targets an old `diffusers` and works through one compatibility alias, so a future `diffusers` upgrade may break it.

**Depth-derived stays as a setting**: needs no download and no time, and is the fallback if a normals model cannot run.

## Decisions still to come

- Phase 2: raw WebGL2 vs Three.js for the live preview shader.
