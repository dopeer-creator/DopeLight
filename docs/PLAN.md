# Dope Light — the plan

This is the whole plan in one place, so any session on any PC can pick the work up. It condenses the user's original project brief (a file that exists only on the laptop) and adds everything the user has asked for since. `CLAUDE.md` says where the work stands right now; `docs/ARCHITECTURE.md` says how what is built works.

## What is being built

A free, local Windows desktop app that relights a photo, modelled on Photoshop's Relight feature. The user opens an image, adds virtual lights, drags and adjusts them live, then renders a realistic result.

Two layers of rendering:

1. **Live preview** — a GPU shader that shades the photo from estimated depth and surface normals. Instant, approximate. It is for placing lights.
2. **Photoreal render** — an AI model (IC-Light) redraws the lighting, guided by the preview. Seconds per image on the GPU. This is the finished look.

Exports: the relit image, and light-only layers the user can blend over the original in an editor.

## Hard constraints

- **Zero cost.** Only free, open-source software and free model weights. No paid APIs, no cloud, no accounts, no telemetry.
- **Fully local.** After the first-run downloads the app works offline.
- **Personal use.** Still, every model's licence is recorded in `docs/LICENSES.md`, with anything non-commercial flagged.
- **Target machine:** Windows 10/11, Ryzen 7 7000, 16 GB RAM, NVIDIA RTX 4050 with **6 GB VRAM**. VRAM is the binding limit: every model must fit; never keep all models loaded at once.
- The preview must stay smooth; a short wait for the photoreal pass is fine.
- It must become an installable app with an auto-updater and a modern, glassy, minimalist interface.

## Tech stack (decided; do not reopen)

Electron + React + TypeScript + Vite (electron-vite) for the app, raw WebGL2 for the preview, Zustand for state. Python 3.11 backend: FastAPI, PyTorch, diffusers, transformers, OpenCV. The backend runs as a child process of Electron on `127.0.0.1` with a per-launch token. Python environment managed by **uv**. Installer by electron-builder (NSIS), updates by electron-updater from GitHub Releases. Models are downloaded on first use, never bundled.

## What the user has added since the brief

These override the brief where they differ.

- **Name: Dope Light** (the brief's working title was "Relight").
- **Logo:** the user's own design, a D lit by a cone of light, gold on dark. Vector source in `app/resources/logo.svg`.
- **Colours:** the whole interface should feel cohesive with the logo: warm near-black, off-white, amber gold.
- **The look to aim for** is in the user's reference pictures (`references/`, kept out of git): Photoshop's Relight panel, and portraits under strong coloured lights. From them:
  - light position by three sliders, Left · Right, Low · High, Close · Far, as well as by dragging;
  - lights can sit in front of or **behind** the subject; a backlight gives a bright rim;
  - **coloured lights must show at full strength**, on the subject and on the background, including dark backgrounds. No cap on how much a light may tint the picture.
- **The lighting must look good and accurate.** The user judged the first preview "not good yet or accurate". Quality of the result is the main thing they care about.
- **Releases on GitHub** for the app (installer and updates).
- **Android:** asked about once; decided desktop first. A phone version, if ever, would be a thin client to the PC backend. Do not start it unasked.
- **Two machines.** Code is written on a laptop without a GPU and on the target PC. Both push to the same GitHub repository.
- **This plan and `CLAUDE.md` must be kept current every turn**, because a session on the other PC starts with no memory of earlier chats.

## Phases

The rule from the brief: do the phases in order, and **stop at the end of each for the user to test**. Do not start the next until they say so. For each phase: build, test what can be tested, measure, fix, update the docs, commit, then report with exactly what to test by hand.

| Phase | What | Status |
| --- | --- | --- |
| 0 | Scaffolding: app shell starts the backend, shows GPU status, leaves no stray processes | done |
| 1 | Preprocess: subject mask, depth, surface normals, session cache, benchmark | done; benchmarked on the RTX 4050 (peak 4.3 GB) |
| 2 | Live preview: shader, light gizmos, sliders, compare, undo/redo, Python reference + parity test | done |
| 3 | Exports: full-size relit image, light layers (8/16-bit, per light) | done; the user confirmed layer + photo = relit |
| 4 | Photoreal pass: IC-Light guided by the preview, ratio transfer to full size, photoreal exports | built; **not yet run on the RTX 4050** |
| 5 | Product polish (see below) | not started |
| 6 | Packaging and updates (see below) | not started |

### Phase 5 — product polish (what the brief asks for)

**Look.** Modern, glassy, minimalist. Dark by default, with a light option. Frameless window with a custom slim title bar. Windows 11 `backgroundMaterial` (mica or acrylic) where available, CSS `backdrop-filter: blur()` otherwise. Translucent floating panels with thin borders, soft shadows, generous spacing, rounded corners (12 to 16 px), one accent colour (now the logo's amber), smooth small animations (150 to 200 ms). A font bundled with the app (Inter or similar; the logo's wordmark uses a rounded geometric sans), no fonts from the network. Icons from lucide. Nothing cluttered.

**First-run setup.** A screen that sets up the Python environment and downloads the models, with clear progress, retry, and a note saying where the files are stored. This must be robust: resumable downloads, checksum verification, clear errors, a "repair environment" button, a log viewer. The app bundles `uv.exe`; on first launch it creates the environment in the data folder and installs pinned dependencies with the PyTorch build that matches the machine (CUDA or CPU). If the pinned requirements change between versions, the environment is re-synced on the next launch. The user also asked that downloads happen up front here rather than when the first image is opened.

**Settings.** Model and cache location; VRAM mode (Low: aggressive offload, or Balanced); default export format; theme; "Clear cache"; "Open logs folder". Also the normals method (DSINE, StableNormal, depth-derived) belongs here.

**Projects.** Save and load as a project file: JSON with the image path and hash, the lights, and the settings. Non-destructive: the original image is never changed. (The brief calls the extension `.relight`; with the new name, ask or use `.dopelight`.) Loading must fill in defaults for settings a saved file lacks.

**Rest.** Error messages that say what happened and what to do. Structured logs in the data folder. Accessibility basics: focus rings, enough contrast, tooltips. Keyboard shortcuts already exist (L, Del, C, Ctrl+Z/Y, Ctrl+O, Ctrl+E, Ctrl+Enter, arrows).

If the visual direction is unclear once this phase starts, ask the user rather than guess.

### Phase 6 — packaging and updates

- electron-builder NSIS installer: per-user install, no admin rights needed. The installer stays small: no PyTorch and no models inside it. The backend's source ships inside the app, so backend updates arrive with app updates.
- electron-updater with the GitHub provider (the repository is public and free). On startup: check in the background, download silently, then a small toast "Update ready, restart to apply". "Check for updates" in settings; a stable/beta channel switch only if it is trivial.
- **No paid code signing.** The README must explain the Windows SmartScreen warning.
- A GitHub Actions workflow that builds and publishes a release when a `v*` tag is pushed: installer, `latest.yml`, and the blockmap.
- A documented test of a full update cycle: install v0.1.0, publish v0.1.1, watch the app update.
- Final README: install, usage, troubleshooting.

Anything that needs the user's GitHub account (creating secrets, changing repository settings) is theirs to do: say what to click or run.

## Things only the RTX 4050 PC can verify

Kept current in `CLAUDE.md` under "Verify on the target PC". The laptop has no NVIDIA GPU, so GPU speed, VRAM use, and half-precision results are never claimed from there.

## When to stop and ask the user

- A model cannot fit in 6 GB even with offloading, or its licence matters.
- Two workable approaches differ in quality against speed and the choice is a matter of taste: show both side by side.
- Anything needing a paid service, an account, or personal credentials.
- Unclear visual direction during Phase 5.

Otherwise decide, write the decision down, and keep going.

## Working rules

- **Verify, do not assume.** Model names, weights, licences, and library APIs change. Check the real source or the installed package before coding against it.
- Run things: the backend, the tests, the app. Look at real output and real screenshots.
- Small, typed functions. `ruff` and `mypy` for Python, strict TypeScript.
- Commit often, one logical change per commit. Never commit model weights or the user's images.
- Prefer boring, reliable solutions. If something cannot be done well within 6 GB or free tooling, say so and propose the closest alternative; do not quietly make it worse.
- Do not add features beyond this plan without asking.
