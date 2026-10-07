# Relight — working notes

Local, free, Photoshop-style image relighting desktop app. Full brief:
`C:\Users\Admin\Downloads\relight-app-claude-code-prompt.md` (read it before any phase).

## Current phase

**Phase 1 (preprocess backend): done.** Benchmark ran on the target PC on 2026-10-07: `cu126` PyTorch sees the RTX 4050, all models ran on the GPU, highest peak VRAM 4326 MB (StableNormal turbo), DSINE preprocess about 3.5 s per image. Numbers are in `docs/ARCHITECTURE.md`. The user already said (2026-10-03) to start Phase 2 after this without asking again.

Next: Phase 2 — live preview (WebGL2 shader per brief section 6.2, gizmos, sliders, compare, undo/redo, Python reference shading + parity test). **Blocked on 2026-10-07: the brief file is not on the target PC.** Do not write the shader from memory of the brief; get the file first.

Git: fresh repository started on the target PC on 2026-10-07 (the laptop's history was not carried over). Remote `origin` is https://github.com/dopeer-creator/DopeLight, branch `main`.

User decisions so far (2026-10-03): desktop first, Android later if at all; build here, benchmark on target PC.

## Machines (important)

- **Build machine:** Dell Latitude 5420, Intel i5-1145G7 (4 cores), Iris Xe, 16 GB RAM. No NVIDIA GPU, no `nvidia-smi`. User folder `C:\Users\Admin`; the paths in this file with `Admin` in them are for that machine.
- **Target machine:** Ryzen 7 7000, 16 GB RAM, RTX 4050 6 GB VRAM. The app is used there. User folder `C:\Users\Asus`, project at `C:\Users\Asus\Downloads\DopeLight` (moved from `Downloads\relight` on 2026-10-07; the old folder still holds the first venv and bench output), uv at `C:\Users\Asus\.local\bin\uv.exe`. Sessions have run here since 2026-10-07.
- Consequence: anything needing CUDA (VRAM numbers, GPU timing, the `cu126` PyTorch build, half precision) cannot be verified here. Build it, test what runs on CPU, and list it under "Verify on target PC" in the phase report. Never claim a VRAM number that was not measured.

## Commands

From repo root:

| What | Command |
| --- | --- |
| First-time setup (picks CPU or CUDA PyTorch) | `npm run setup` |
| Run app (Electron + backend) | `npm run dev` |
| All checks (typecheck, ruff, mypy, pytest) | `npm run check` |
| Download the 4 sample photos | `npm run samples` |
| Preprocess benchmark → `bench-out/` | `npm run bench` |
| Real server end-to-end check | `npm run e2e` |
| Orphan process check | `powershell -File scripts/check-orphans.ps1` |

- **Never run plain `uv run` or `uv sync` in `backend/`.** Without `--extra cpu` / `--extra cu126` uv swaps PyTorch for the default PyPI build. Root scripts use `node scripts/uv.mjs run --no-sync`; setup uses `scripts/setup-backend.mjs`. Both find uv through `scripts/find-uv.mjs` (PATH first, then `~/.local/bin` and the WinGet folder), because a terminal opened before uv was installed keeps the old PATH.
- Bench options: `uv run --no-sync --directory backend python -m relight_backend.bench --help` (`--normals`, `--working-edge`, `--fresh`).
- Backend alone: in `backend/`, set `RELIGHT_TOKEN=x`, run `.venv\Scripts\python -m relight_backend.main --port 8765`.
- Dev screenshot helper: set `RELIGHT_SCREENSHOT=<path.png>` before `npm run dev`; main saves a capture 6 s after each page load.

## Decisions

- **Versions:** Electron 44, `electron-vite` 5, Vite 7 (not 8: `electron-vite` 5 supports up to 7), React 19, TypeScript 5.9, Zustand 5. Python 3.11 via uv, FastAPI, PyTorch 2.14, transformers 5, diffusers 0.40.
- **PyTorch build:** extras `cpu` and `cu126` in `backend/pyproject.toml`, mutually exclusive. `cu126` chosen for the RTX 4050 (works with older drivers than `cu130`). Not yet run on the target.
- **App name:** `APP_NAME` in `app/src/shared/constants.ts` and `backend/relight_backend/constants.py`. Also `<title>` in `app/src/renderer/index.html` and `name` in `app/package.json`.
- **Backend launch:** Electron main picks a free port, makes a random token, spawns the venv Python. Token goes through env var `RELIGHT_TOKEN`. All endpoints need `Authorization: Bearer <token>`.
- **No orphans:** backend gets `--parent-pid` and waits on that process handle; plus `taskkill /T /F` on normal quit. (Phase 0 used "exit when stdin closes". That broke once PyTorch was installed: on Windows a thread blocked reading the stdin pipe made `import torch` hang in another thread, so `/health` never answered. Do not go back to stdin watching.)
- **Lazy heavy imports:** `main.py` must not import torch/transformers at module level; jobs import them. `models/specs.py` is pure data for the same reason.
- **Models (pinned in `models/specs.py`):** mask BiRefNet lite; depth Depth Anything V2 Small; normals DSINE (default), StableNormal turbo, or depth-derived.
- **Map conventions:** depth 16-bit, white = near; normals camera space +X right, +Y up, +Z to viewer; `DEPTH_SCALE = 0.4`. Full table in `docs/ARCHITECTURE.md`. Phase 2 shader must match.
- **DSINE quirks:** raw output has X pointing left (wrapper flips it). Its encoder library `geffnet` tries to download ImageNet weights at construction; the wrapper forces `pretrained=False`. Its repo zip is 168 MB of PDFs/GIFs, so only 3 source files are fetched.
- **StableNormal quirks:** code targets diffusers 0.28; the wrapper aliases `diffusers.models.controlnet` to its new location. X also flipped. Only the turbo (one-step YOSO v0.3) variant is used; the full two-stage model is too big for 6 GB.
- **Downloads:** separate process (`utils/fetch_weights.py`) so cancel = kill; `HF_HUB_DISABLE_XET=1` there because the Xet transfer path does not report progress through the progress-bar hook. Server runs with `HF_HUB_OFFLINE=1`.
- **Not built, on purpose:** rembg/isnet mask fallback (BiRefNet lite worked); albedo shading-flattening toggle (brief says only if it visibly helps; revisit in Phase 2 when lighting is visible).
- **Electron binary:** Electron 44 has no npm install script; `app/package.json` `postinstall` runs `install-electron`. `esbuild` is approved in `allowScripts`.
- **Packaged paths (not built yet):** backend source in `resources/backend`, venv in `%APPDATA%/Relight/venv`. First-run venv creation is Phase 5/6.

## Known issues / quirks

- **Claude desktop app sandbox:** shells started by Claude redirect writes under `%APPDATA%` into the Claude package folder. Two effects: (1) uv's managed Python breaks with `Missing expected target directory for Python minor version link`; set `$env:UV_PYTHON_INSTALL_DIR = "C:\Users\Admin\.uv-python"` before any `uv` command. (2) App data would land in the redirected folder; set `$env:RELIGHT_DATA_DIR = "C:\Users\Admin\Downloads\relight\.data"` when running backend, bench, or e2e from a Claude shell. All four models (3.9 GB) are already downloaded there. A normal user terminal needs neither.
- uv is not on PATH in Claude shells: `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`.
- Background commands from Claude are killed after 10 minutes; start long jobs (bench, big downloads) with `Start-Process` and poll the log.
- StableNormal turbo needs ~7 GB RAM on CPU; with 16 GB and other apps open this machine swaps.
- `gh` (GitHub CLI) is not installed; needed in Phase 6 or the user creates the repo by hand.
- Renderer bundle is ~650 kB unsplit; fine for a local app.

## Verify on target PC (not possible here)

- Done 2026-10-07: `npm run setup` picks `cu126` and PyTorch sees the GPU; `npm run bench` peak VRAM per model under 5.5 GB; half-precision sheets look right.
- Still open: status bar shows the GPU name and free VRAM (needs `npm run dev` on the target PC).

## Rules carried from the brief

- Stop at the end of each phase with a manual test list. Commit often, one logical change per commit. No model weights or user images in git.
- No AI attribution lines in commits or PRs (user preference).
- Verify model names, licenses, and library APIs against real sources before coding against them.
