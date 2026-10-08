# Dope Light — handoff and working notes

**Read this first, every session.** A session on either PC starts with no memory of earlier chats. This file and `docs/PLAN.md` are the memory. They were set up at the user's request on 2026-10-08, and they must be kept true.

- `docs/PLAN.md` — the whole plan: what is being built, the hard limits, every phase and what it must contain, and what the user has asked for since the original brief. It is enough to build any phase from; the brief file itself exists only on the laptop.
- `docs/ARCHITECTURE.md` — how what is built works, with measured numbers.
- `docs/LICENSES.md` — every model and library, with licence.
- This file — where the work stands, how to work with the user, commands, decisions, quirks.

**Keep it current.** Before ending any turn that changed something, update "Where things stand" below (and `docs/PLAN.md` if the plan itself changed), commit, and push. The other PC only knows what is pushed.

## How the user wants to work

- **Plain language.** Explain progress simply: what works now, what he has to do, how it is structured, how it was tested. Short sentences, no jargon without a quick gloss, no walls of text.
- **Honest reports.** Say what was checked and what was not. Never claim a GPU number from the laptop. If something looks wrong, say so before being asked.
- **He judges by the look.** He sends screenshots and reference pictures; treat them as the specification. When you can, show pictures rather than describe.
- **Stop at the end of each phase** and give him an exact list of what to test. Do not start the next phase until he says "go".
- **Git:** commits and pushes go under GitHub id `Prathamgit9` (`Pratham <139778459+Prathamgit9@users.noreply.github.com>`), never the laptop's default id. No AI attribution lines ("Co-Authored-By", "Generated with") in commits or pull requests.
- Do not commit his reference pictures or test photos (third-party images; the repository is public).

## Where things stand

*Last updated: 2026-10-08, from the laptop. The user works on the RTX 4050 PC next; this section is written for that session.*

### Start here (GPU PC)

1. `git pull`, then `npm run setup` (dependencies may have changed), then `npm run check`.
2. Check the git identity before any commit: `git config user.name` and `git config user.email` in this repo must be `Pratham` / `139778459+Prathamgit9@users.noreply.github.com`. Set them repo-locally if not.
3. Ask the user to put his fighter photo at `samples/fighter.jpg` (it is not in git; `samples/` is ignored). Any of his own photos will also do.
4. Run the first-ever photoreal render on the GPU, at full default size:

   ```
   node scripts/uv.mjs run --no-sync --directory backend python ../scripts/render_scene.py ../samples/fighter.jpg ../docs/scenes/fighter-yellow-top-red-trim.json ../render-out/fighter
   ```

   The first run downloads the photoreal models (3.7 GB). It prints the time, the device, and the peak VRAM, and writes `render-out/fighter/sheet.jpg`: original, preview shading, raw model output, result. **Look at the sheet yourself and show it to the user.** Record the time and peak VRAM in `docs/ARCHITECTURE.md` (Photoreal pass) and tick the Phase 4 line under "Verify on target PC". The peak must stay under 5.5 GB.
5. Then do the same through the app (`npm run dev`, open the photo, place lights, Render), since that is what the user will use.
6. Then work down "The work list" below, showing the user a sheet after each change.

### What the user wants (his words, 2026-10-08)

- **No redrawing.** His pixels stay. An earlier idea of a "how much may the AI redraw" control is rejected; do not bring it back.
- **Crisp, accurate light**, like Photoshop's Relight: see `references/` (Photoshop screenshots with blue and red lights; on the laptop only, ask him for them). He also sent a ChatGPT-generated picture of the fighter: that one *is* a redraw, and it is a reference **only for how crisp the light looks** (a visible shaft of light from above, deep shadow on the subject, a red rim, a real cast shadow on the floor).
- His brief for the fighter photo: a yellow spotlight from the top, a red trim spotlight from the right, the subject a little darker, and **cast shadows that read** ("cast shadows are as important"). The scene file `docs/scenes/fighter-yellow-top-red-trim.json` is that setup.
- **Try different lighting setups, not the same one twice.** Vary colour, direction, light type, how dark the base is.
- The background must take the light and its colour too. No cap on how strongly a light tints.
- His verdict so far: ours was weak and soft; Clipdrop's Relight was better but "not good enough either".

### What was built last (commit `6845a6b`), and what the test showed

`photoreal.add_preview_detail` splits the light in two. The broad light (where it falls, how it fades) stays the AI model's. The fine light (the edge along a muscle, a fold, a rim) comes from the preview shaded at the full working size, where it is exact per pixel. Before this, the model's light was measured at diffusion size and smoothed, which made everything mushy.

Tested on the laptop only (CPU, model at 320 x 512, 12 steps, 92 s). Honest reading of that picture:

- Better: the red light along the abs, arm and hand wraps is now sharp, and the light follows the muscles.
- **New fault, most visible:** the preview's flaws now show sharp too. The spotlight's cone leaves a hard straight diagonal edge on the back wall, and the cast shadow on the floor has a jagged, dotted edge (the shadow ray-march's jitter). Before, the smoothing hid both.
- The black shorts came out blue-grey: the model repaints them pale, and the 2.5 times brightness leash still lets some of that through.
- The result is now close to the preview's own shading. So **the preview's quality is the ceiling**, and the preview is where the work is.
- Unknown: how it looks at real size on the GPU. Nothing here was ever run on the RTX 4050.

### The work list, in order

1. **Measure and look on the GPU** (steps 4 and 5 above). Some softness may simply be the laptop's tiny render size.
2. **Clean cast shadows in the preview.** The dotted, jagged shadow edge must go: more ray-march steps or a better jitter pattern, then a small edge-keeping blur on the shadow term only (not on the whole light). Shadow shapes come from a heightfield guessed from depth, so they are approximate; aim for clean and plausible. Shader and Python twin must change together (`gl/shader.ts`, `pipeline/shading.py`, then `npm run parity`).
3. **Spotlight cone edge.** On the wall it reads as a hard triangle. Check `coneSoftness` in the scene first (0.5 to 0.6 there); if the falloff curve itself is too hard, soften it. A real spot's edge is soft on a far wall.
4. **Visible light shaft (haze)** for spotlights, in the shader and in the hint. This is a large part of why his reference picture looks dramatic. Make it a per-light setting, default off or low.
5. **Decide what the model is still for.** With the fine light from the preview, the model only adds broad realism, and its repainting still leaks (the shorts). Try: a tighter `BRIGHTNESS_LEASH`, a higher "Follow lights" value, and the preview alone (no model). Show the user the versions side by side and let him pick; this is a matter of taste.
6. **A prompt written from the lights** (colours, directions, mood) in place of the fixed "beautiful lighting, natural", if step 5 keeps the model.
7. `DETAIL_LIMIT` (2.5) bounds how much the fine light may differ from the broad light. Raise it if crisp edges look clipped, lower it if noise shows.

Be honest with the user about the ceiling: a free model that fits 6 GB will not equal a large cloud generator, and with no redrawing allowed, the look depends on the estimated depth and normals being right.

### Phases

Phases 0 to 4 are built. Phase 4 is still being tuned for the look (above), and the user has not accepted it. **Do not start Phase 5 until he says "go".**

- **Phase 5** on his "go": first-run setup (Python environment, model downloads with progress), settings, project save/load, glass UI polish, a bundled font. Details in `docs/PLAN.md`.
- **Phase 6** after that: installer, auto-update, GitHub releases. It needs Phase 5's first-run setup first, because a packaged app has no Python environment.

Open question for later: the project file extension (`.relight` in the brief) should probably be `.dopelight`; ask when Phase 5 reaches it.

### Lessons already paid for (do not relearn)

- Measure the lighting ratio between *smoothed* pictures, never pixel by pixel: dark areas turn to blotches.
- The model repaints (black shorts became pale cloth). Keep its brightness on a leash to the preview's, take colour from the user's lights where they land, and take only the subject from the model; the background gets the preview's light.
- The dark-surface floor `ALBEDO_FLOOR` stays small (0.02); at 0.06 a strong spot turned black cloth grey.
- Placement matters as much as code: a top spot in front of the subject throws wing-shaped shadows on the wall; directly overhead (depth about equal to the subject's) the shadow falls on the floor.
- A dark photo shows faults a bright portrait hides. Test on both.

History, for context: Phase 1 was benchmarked on the target PC on 2026-10-07 (highest peak VRAM 4326 MB). Phase 3 was confirmed by the user (light layer + photo = relit export). The user called the first preview "not good yet or accurate"; since then: lights stop at the sky, no default shine, Smooth surface and Even light settings, lights behind the subject with a rim, Photoshop-style position sliders, colour of light uncapped. Desktop first; Android later if at all.

Git: remote `origin` is https://github.com/dopeer-creator/DopeLight, branch `main`. Both machines push there, so `git fetch` and look at `origin/main` before starting work. (The laptop's pre-GitHub history is on its local branch `laptop-history`.)

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
| Shader vs Python reference, pixel comparison | `npm run parity` |
| Real app driven by a script (drag, keys, sliders) | `npm run ui-smoke` |
| Orphan process check | `powershell -File scripts/check-orphans.ps1` |
| Photoreal render of one photo + scene file, no window | `scripts/render_scene.py` (usage at the top of the file) |

- **Never run plain `uv run` or `uv sync` in `backend/`.** Without `--extra cpu` / `--extra cu126` uv swaps PyTorch for the default PyPI build. Root scripts use `node scripts/uv.mjs run --no-sync`; setup uses `scripts/setup-backend.mjs`. Both find uv through `scripts/find-uv.mjs` (PATH first, then `~/.local/bin` and the WinGet folder), because a terminal opened before uv was installed keeps the old PATH.
- Bench options: `uv run --no-sync --directory backend python -m relight_backend.bench --help` (`--normals`, `--working-edge`, `--fresh`).
- Backend alone: in `backend/`, set `RELIGHT_TOKEN=x`, run `.venv\Scripts\python -m relight_backend.main --port 8765`.
- Dev helpers are environment variables read by `app/src/main/dev.ts`, set before `npm run dev`: `RELIGHT_OPEN=<image>` opens it; `RELIGHT_SCENE=<json>` loads `{lights, globals, split?}`; `RELIGHT_SCREENSHOT=<png>` saves a capture once the image is drawn (or 6 s after load with no image); `RELIGHT_BENCH=1` logs shader time at 1080p and 4K; `RELIGHT_SCRIPT=<js>` runs a script in the page. This is how to check the UI without a human.
- Renaming or moving the repo folder breaks `backend/.venv` (its launchers store absolute paths): delete it and run `node scripts/setup-backend.mjs`.

## Decisions

- **Versions:** Electron 44, `electron-vite` 5, Vite 7 (not 8: `electron-vite` 5 supports up to 7), React 19, TypeScript 5.9, Zustand 5. Python 3.11 via uv, FastAPI, PyTorch 2.14, transformers 5, diffusers 0.40.
- **PyTorch build:** extras `cpu` and `cu126` in `backend/pyproject.toml`, mutually exclusive. `cu126` chosen for the RTX 4050 (works with older drivers than `cu130`). Not yet run on the target.
- **App name: Dope Light** (the user's decision, 2026-10-08; "Relight" was the brief's working title). Set in `APP_NAME` in `app/src/shared/constants.ts` and `backend/relight_backend/constants.py`, `<title>` in `app/src/renderer/index.html`, `productName` in `app/package.json`. Internal identifiers keep the old word on purpose: the Python package `relight_backend`, the `RELIGHT_*` environment variables. The data folder is `%APPDATA%\Dope Light`; an existing `%APPDATA%\Relight` is renamed to it on first start (`app/src/main/migrate.ts`, `utils/paths.py`) so models are not downloaded again.
- **Logo:** the user's design, redrawn as vector in `app/resources/logo.svg` (a D lit by a cone of light, gold on dark; wordmark "dope" off-white + "light" amber). `npm run icons` renders `icon.png` and `icon.ico` from it. The UI palette follows the logo at the user's request (2026-10-08): warm near-black, off-white text, amber accent; all colours are variables at the top of `app/src/renderer/src/styles.css`.
- **Releases on GitHub:** the user asked for them on 2026-10-08. That is Phase 6 (NSIS installer, auto-update, release workflow) and needs Phase 5's first-run setup first (a packaged app has no Python environment yet: bundle `uv`, create the venv in the data folder, download models with a progress screen).
- **Backend launch:** Electron main picks a free port, makes a random token, spawns the venv Python. Token goes through env var `RELIGHT_TOKEN`. All endpoints need `Authorization: Bearer <token>`.
- **No orphans:** backend gets `--parent-pid` and waits on that process handle; plus `taskkill /T /F` on normal quit. (Phase 0 used "exit when stdin closes". That broke once PyTorch was installed: on Windows a thread blocked reading the stdin pipe made `import torch` hang in another thread, so `/health` never answered. Do not go back to stdin watching.)
- **Lazy heavy imports:** `main.py` must not import torch/transformers at module level; jobs import them. `models/specs.py` is pure data for the same reason.
- **Models (pinned in `models/specs.py`):** mask BiRefNet lite; depth Depth Anything V2 Small; normals DSINE (default), StableNormal turbo, or depth-derived.
- **Map conventions:** depth 16-bit, white = near; normals camera space +X right, +Y up, +Z to viewer; `DEPTH_SCALE = 0.4`. Full table in `docs/ARCHITECTURE.md`. Phase 2 shader must match.
- **DSINE quirks:** raw output has X pointing left (wrapper flips it). Its encoder library `geffnet` tries to download ImageNet weights at construction; the wrapper forces `pretrained=False`. Its repo zip is 168 MB of PDFs/GIFs, so only 3 source files are fetched.
- **StableNormal quirks:** code targets diffusers 0.28; the wrapper aliases `diffusers.models.controlnet` to its new location. X also flipped. Only the turbo (one-step YOSO v0.3) variant is used; the full two-stage model is too big for 6 GB.
- **Downloads:** separate process (`utils/fetch_weights.py`) so cancel = kill; `HF_HUB_DISABLE_XET=1` there because the Xet transfer path does not report progress through the progress-bar hook. Server runs with `HF_HUB_OFFLINE=1`.
- **Shading (Phase 2):** formulas and the departures from the brief are in `docs/ARCHITECTURE.md` (`Live preview`). Shader in `app/src/renderer/src/gl/shader.ts`, Python twin in `backend/relight_backend/pipeline/shading.py`; numbers shared through `SHADING` in `app/src/shared/lighting.ts` and guarded by `tests/test_shading.py`. Change both sides together and run `npm run parity`.
- **Preview details:** raw WebGL2 (no Three.js). Depth goes to the GPU as float from `/session/{id}/depth_raw` (16-bit PNGs lose precision in browsers). Bitmaps are decoded with colour management off. `gl.finish()` does not wait in Chromium; timing uses a 1-pixel `readPixels`. Dragging renders at reduced resolution when a full frame exceeds 14 ms.
- **Lights behind the surface (user asked 2026-10-08 to move lights in front of and behind the subject):** a light whose `z` is below the surface under it switches its shadows from solid shapes to 0.15-thick shells, judged from a dilated depth channel; details in `docs/ARCHITECTURE.md`. The slider is labelled Depth; the gizmo turns dashed when behind.
- **References (2026-10-08):** `references/` (git-ignored, third-party images) shows the target: Photoshop's Relight panel and a six-way relit portrait. Built from it: Left · Right / Low · High / Close · Far sliders and the rim light for lights behind a shape. The realism of those faces is Phase 4's job.
- **Git identity:** the user wants commits and pushes to this repo under GitHub id `Prathamgit9` (repo-local `user.name` / `user.email` are set to it on the laptop), not the laptop's global id `prathamcytoxindia-del`.
- **Export (Phase 3):** backend renders at full size in ~1 MP row strips with `shade_scene(rows=...)`; layers are exact differences so base + layer = relit under Add, with two blend targets (gamma-space editors, linear-light editors); details and measured tolerances in `docs/ARCHITECTURE.md`. File writes go through `cv2.imencode` + Python I/O because OpenCV cannot open non-ASCII paths on Windows. Window filters at full size must be separable (`_window_max`); a square 49-pixel pool on 18 MP took a minute.
- **Screenshots can be stale:** a covered window or sleeping display stops painting; `dev.ts` forces a repaint before capture. If a capture shows an impossible state, check `page loaded` / `renderer process gone` in the log before suspecting the app.
- **Preview quality fixes (2026-10-08, after the user's first real test looked bad):** lights do not reach the sky (reach map from raw inverse depth), new lights have specular 0, scene settings Smooth surface (0.3) and Even light (0.5). Table in `docs/ARCHITECTURE.md`. `GlobalSettings` gained `smoothing` and `flatten`; anything loading saved settings must merge defaults (`lightsStore.reset` does). The user's verdict before these fixes: the lighting "doesnt look good yet or accurate"; Phase 4 is expected to close that gap.
- **Photoreal (Phase 4):** IC-Light `fc` weights are offsets merged onto Realistic Vision 5.1 (SD 1.5), ported from the official `gradio_demo.py`. The whole photo is the condition (no background removal, so the scene is kept); the hint is the preview's own relit shading at diffusion size and becomes the starting latent; "Follow lights" maps to denoise 0.95 (loose) .. 0.5 (tight). Only a lighting ratio is kept and applied to the full-size original, so detail and identity stay: **brightness from the model (leashed to within 2.5 times of the preview's), colour from the user's lights in full wherever they land (the model's colour elsewhere)**, subject only; the background takes the hint's ratio. Ratios are taken between guided-filtered pictures. The fine light is then put back from the preview shaded at the full working size (`add_preview_detail`), so edges of light are crisp; this also makes the preview's own flaws show. The ratio is applied as `(orig + e) * R - e` so black areas can gain light. The user's Photoshop references (2026-10-08) want strong coloured light on subject and background; do not reintroduce a colour cap. Renders live in `<session>/renders/<id>/` (`ratio.npy`, `preview.jpg`, plus `hint.jpg` and `diffusion.jpg` for inspection). OOM: retry at 0.8x and 0.64x size with sequential offload. Models: 3.7 GB (`specs.PHOTOREAL`).
- **Lights:** up to 8; spot/directional aim at a `target` point rather than storing a direction; colour stored as linear RGB. Opening an image adds one starter light.
- **Not built, on purpose:** rembg/isnet mask fallback (BiRefNet lite worked); albedo shading-flattening toggle (brief says only if it visibly helps; revisit in Phase 2 when lighting is visible).
- **Electron binary:** Electron 44 has no npm install script; `app/package.json` `postinstall` runs `install-electron`. `esbuild` is approved in `allowScripts`.
- **Packaged paths (not built yet):** backend source in `resources/backend`, venv in `%APPDATA%/Relight/venv`. First-run venv creation is Phase 5/6.

## Known issues / quirks

- **Claude desktop app sandbox:** shells started by Claude redirect writes under `%APPDATA%` into the Claude package folder. Two effects: (1) uv's managed Python breaks with `Missing expected target directory for Python minor version link`; set `$env:UV_PYTHON_INSTALL_DIR = "C:\Users\Admin\.uv-python"` before any `uv` command. (2) App data would land in the redirected folder; set `$env:RELIGHT_DATA_DIR = "C:\Users\Admin\Downloads\DopeLight\.data"` when running the app, backend, bench, e2e, or ui-smoke from a Claude shell. All four models (3.9 GB) are already downloaded there. A normal user terminal needs neither.
- uv is not on PATH in Claude shells: `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`.
- Background commands from Claude are killed after 10 minutes; start long jobs (bench, big downloads) with `Start-Process` and poll the log.
- StableNormal turbo needs ~7 GB RAM on CPU; with 16 GB and other apps open this machine swaps.
- `gh` (GitHub CLI) is not installed; needed in Phase 6 or the user creates the repo by hand.
- Renderer bundle is ~650 kB unsplit; fine for a local app.

## Verify on target PC (not possible here)

- Done 2026-10-07: `npm run setup` picks `cu126` and PyTorch sees the GPU; `npm run bench` peak VRAM per model under 5.5 GB; half-precision sheets look right.
- Still open: status bar shows the GPU name and free VRAM (needs `npm run dev` on the target PC).
- Phase 4, still open: a photoreal render at the default size with the detail pass on the RTX 4050: time, peak VRAM under 5.5 GB (the job result reports both), and whether the look holds up on the user's own photos.
- Phase 3, still open: export a real photo on the target PC and time it (laptop CPU: 20 s relit, 137 s with a shadowed light, 18 MP); place a light layer over the photo with Add in the user's editor and compare with the relit export.
- Phase 2, still open: `npm run parity` passes on the NVIDIA driver; `npm run ui-smoke` passes; frame times with `RELIGHT_BENCH=1` (laptop Intel graphics: 8 lights with shadows 47 ms at 1080p); dragging feels smooth on a 4K photo.

## Rules carried from the brief

The full list is in `docs/PLAN.md` ("Working rules", "When to stop and ask the user"). The ones broken most easily:

- Stop at the end of each phase with a manual test list. Commit often, one logical change per commit. No model weights or user images in git.
- Verify model names, licences, and library APIs against real sources before coding against them.
- Never claim a speed or VRAM number that was not measured on the machine it is about.
