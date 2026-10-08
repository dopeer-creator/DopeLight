# Relight

Local, free image relighting for Windows. Open an image, add virtual lights, drag them, and export the relit image or a light-only layer. Everything runs on your own PC; no accounts, no cloud, no telemetry.

**Status:** Phase 3 of 6. You can open an image, relight it live with up to 8 lights, and export the result or light-only layers at full size. The photoreal pass comes next.

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

## Photoreal render

The live preview is a fast guide. **Render** (or Ctrl+Enter) redraws the photo's lighting with an AI model (IC-Light), following the lights you placed, then applies only the change in light to your full-size photo, so its detail stays.

- **Describe light** (optional): a few words on the mood, like "warm sunset light".
- **Follow lights**: high keeps the light where you put it; low gives the model more freedom.
- **Steps**, **Seed**, **Extra detail pass**: quality against time.

It needs about 3.7 GB of models (downloaded the first time) and an NVIDIA GPU to be quick. Without a GPU it works but takes minutes. After a render, switch between **Preview** and **Photoreal** at the top; moving a light marks the render as old.

## Exporting

**Export** (or Ctrl+E) saves at the original image's full size:

- **Relit image**: the finished picture.
- **Light layer**: only what the lights add, on black. Put it over your photo in an editor and set the layer's blend mode to **Add** (Photoshop calls it Linear Dodge (Add)). Pick who it is made for: Photoshop / Affinity / Krita, or GIMP / 32-bit documents; the two add colours differently.
- **One layer per light**: the same, split by light, so you can rebalance lights later.

With a photoreal render you can export that instead: the relit image, a light layer (approximate: it cannot hold the shadows the render added), or a **multiply layer** that holds both brightening and shadows, for the Multiply blend mode in a 32-bit document.

Formats: PNG (8 or 16-bit), JPEG, TIFF. A layer can only add light. If you changed Original light, Ambient, or Exposure, the layers belong on the adjusted picture, which is saved next to them as `_base`. The original file is never changed.

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
