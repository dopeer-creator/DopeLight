# Relight

Local, free image relighting for Windows. Open an image, add virtual lights, drag them, and export the relit image or a light-only layer. Everything runs on your own PC; no accounts, no cloud, no telemetry.

**Status:** Phase 1 of 6. The backend turns an image into the maps relighting needs (subject mask, depth, surface normals). The app window opens and shows backend and GPU status; the lighting UI arrives in Phase 2.

## Requirements

- Windows 10/11
- [Node.js](https://nodejs.org) 22.12 or newer
- [uv](https://docs.astral.sh/uv/) (`winget install astral-sh.uv`)
- NVIDIA GPU with 6 GB VRAM for real use. Without one everything still runs on the CPU, slowly.
- About 4 GB of disk for models (0.6 GB without the optional StableNormal model)

## Run from source

```bash
npm run setup
```

```bash
npm run dev
```

`setup` installs the app's packages and creates the Python environment in `backend/.venv`. It checks for an NVIDIA GPU and installs the matching PyTorch build (CUDA 12.6, or CPU-only). `dev` starts the app, which starts the backend itself.

## Benchmark the preprocess step

```bash
npm run samples
```

```bash
npm run bench
```

`samples` downloads four public-domain test photos into `samples/`. `bench` runs mask, depth, and all three normals methods on each, downloading models on first run. Results land in `bench-out/`: one side-by-side sheet per image, plus `report.md` with time and peak VRAM per model. To test your own photos, put them in `samples/` first.

## Checks

```bash
npm run check
```

Runs TypeScript type checks, `ruff`, `mypy`, and the backend tests.

```bash
npm run e2e
```

Starts the real backend and drives it over HTTP: upload, progress stream, maps, cache hit, cancel. Needs the models (run the benchmark once first).

## Where files are stored

`%APPDATA%\Relight\` holds `models\` (downloaded weights), `sessions\` (maps per opened image), and `logs\`. Set the `RELIGHT_DATA_DIR` environment variable to use another folder.

## Layout

- `app/` — Electron + React desktop app
- `backend/` — Python FastAPI server that runs the models
- `docs/` — [architecture](docs/ARCHITECTURE.md) and [licenses](docs/LICENSES.md)
- `scripts/` — setup, sample download, end-to-end check

Installer, auto-update, usage guide, and troubleshooting are added in Phase 6.
