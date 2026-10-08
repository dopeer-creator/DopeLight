# Relight

Local, free image relighting for Windows. Open an image, add virtual lights, drag them, and export the relit image or a light-only layer. Everything runs on your own PC; no accounts, no cloud, no telemetry.

**Status:** Phase 2 of 6. You can open an image and relight it live with up to 8 lights. Export and the photoreal pass come in the next phases.

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

## Using it

- **Open** an image with the button, Ctrl+O, drag and drop, or paste. The first open of an image takes a few seconds (longer without a GPU) while its depth and surface maps are computed; later opens are instant.
- **Drag** a light's dot to move it. **Mouse wheel** over the picture (or the Depth slider) moves the selected light toward or away from you. Below the surface under it, the light is behind that part of the photo: the dot turns dashed, and it lights the background and rims edges.
- Spot and Sun lights have a second small ring: where the light aims.
- **L** adds a light, **Del** deletes the selected one, **arrow keys** nudge it (Shift for bigger steps), **Ctrl+Z / Ctrl+Y** undo and redo, hold **C** to see the original. **Split** shows original and relit side by side.

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

```bash
npm run parity
```

Renders 19 test scenes with the app's shader and with the Python reference and compares the pixels.

```bash
npm run ui-smoke
```

Starts the real app, opens a sample photo, and acts like a user (drag, wheel, keys, sliders), checking the result of each step.

## Where files are stored

`%APPDATA%\Relight\` holds `models\` (downloaded weights), `sessions\` (maps per opened image), and `logs\`. Set the `RELIGHT_DATA_DIR` environment variable to use another folder.

## Layout

- `app/` — Electron + React desktop app
- `backend/` — Python FastAPI server that runs the models
- `docs/` — [architecture](docs/ARCHITECTURE.md) and [licenses](docs/LICENSES.md)
- `scripts/` — setup, sample download, end-to-end check

Installer, auto-update, usage guide, and troubleshooting are added in Phase 6.
