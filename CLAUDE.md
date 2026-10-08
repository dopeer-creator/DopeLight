# Dope Light — handoff and working notes

**Read this first, every session.** A session on either PC starts with no memory of earlier chats. This file and `docs/PLAN.md` are the memory. They were set up at the user's request on 2026-10-08, and they must be kept true.

- `docs/PLAN.md` — the whole plan: what is being built, the hard limits, every phase and what it must contain, and what the user has asked for since the original brief. It is enough to build any phase from; the brief file itself exists only on the laptop.
- `docs/ARCHITECTURE.md` — how what is built works, with measured numbers.
- `docs/LICENSES.md` — every model and library, with licence.
- `docs/CHANGELOG.md` — what each session changed, newest first. Add an entry before ending a session.
- `handoff/` — the user's pictures (`pictures/`) and this app's results (`results/`), so both PCs see the same evidence.
- This file — where the work stands, how to work with the user, commands, decisions, quirks.

**Keep it current.** Before ending any turn that changed something, update "Where things stand" below and `docs/CHANGELOG.md` (and `docs/PLAN.md` if the plan itself changed), put the pictures worth seeing in `handoff/results/`, commit, and push, unfinished branches included. The other PC only knows what is pushed. The user asked for exactly this on 2026-10-08.

## How the user wants to work

- **Plain language.** Explain progress simply: what works now, what he has to do, how it is structured, how it was tested. Short sentences, no jargon without a quick gloss, no walls of text.
- **Honest reports.** Say what was checked and what was not. Never claim a GPU number from the laptop. If something looks wrong, say so before being asked.
- **He judges by the look.** He sends screenshots and reference pictures; treat them as the specification. When you can, show pictures rather than describe.
- **Stop at the end of each phase** and give him an exact list of what to test. Do not start the next phase until he says "go".
- **Git:** commits and pushes go under GitHub id `Prathamgit9` (`Pratham <139778459+Prathamgit9@users.noreply.github.com>`), never the laptop's default id. No AI attribution lines ("Co-Authored-By", "Generated with") in commits or pull requests.
- Do not commit his reference pictures or test photos anywhere but `handoff/` (third-party images; the repository is public). He ordered `handoff/pictures/` himself, added the cameraman photo to it himself, and asked for the result pictures to be pushed too (`handoff/results/`). All of `handoff/` is to be removed later, when he says so.

## Where things stand

*Last updated: 2026-10-08 (late), from the RTX 4050 PC. Earlier the same day the laptop built Phases 2 to 4. `docs/CHANGELOG.md` lists what each session did.*

### Start here (either PC)

1. `git pull`, then `npm run setup` (dependencies may have changed), then `npm run check`.
2. Check the git identity before any commit: `git config user.name` and `git config user.email` in this repo must be `Pratham` / `139778459+Prathamgit9@users.noreply.github.com`. Set them repo-locally if not. On the GPU PC the remote URL names the account (`https://Prathamgit9@github.com/...`) and pushing from a Claude shell works.
3. Look at the pictures before doing anything else; they are the specification and the evidence:
   - `handoff/pictures/` — the user's test photos and reference pictures, each explained in its `README.md`.
   - `handoff/results/` — what this app produced, session by session, with a `README.md` saying what each picture shows.
4. Test photos: `npm run samples` downloads four free ones. The user's own are `handoff/pictures/fighter.jpg` and `handoff/pictures/types-of-shots-in-film.jpg` (the cameraman, **the current subject**). Lighting setups are in `docs/scenes/`.
5. To judge a change to the shading, without the AI model (a second or two):

   ```
   node scripts/uv.mjs run --no-sync --directory backend python ../scripts/render_scene.py ../handoff/pictures/types-of-shots-in-film.jpg ../docs/scenes/cameraman-orange-rim.json ../render-out/cameraman --preview-only
   ```

   Without `--preview-only` it runs the photoreal pass too (GPU: about 35 s) and writes `sheet.jpg`: original, preview shading, raw model output, result. **Look at the pictures yourself and show them to the user.**
6. The user restarts the app (`npm run dev`) to get backend changes; a running app keeps the old code.

### What the user wants (his words, 2026-10-08)

- **No redrawing.** His pixels stay. An earlier idea of a "how much may the AI redraw" control is rejected; do not bring it back.
- **Crisp, accurate light**, like Photoshop's Relight: see `handoff/pictures/photoshop-relight-*.png` (Photoshop screenshots with blue and red lights). He also sent a ChatGPT-generated picture of the fighter: that one *is* a redraw, and it is a reference **only for how crisp the light looks** (a visible shaft of light from above, deep shadow on the subject, a red rim, a real cast shadow on the floor).
- His brief for the fighter photo: a yellow spotlight from the top, a red trim spotlight from the right, the subject a little darker, and **cast shadows that read** ("cast shadows are as important"). The scene file `docs/scenes/fighter-yellow-top-red-trim.json` is that setup.
- **The cameraman photo is next** (late 2026-10-08): "more complex", "a lot of potential for testing". He wants to **change the light colour and add a rim light to the man**; in the app he could not get a rim on him.
- **Try different lighting setups, not the same one twice.** Vary colour, direction, light type, how dark the base is.
- The background must take the light and its colour too. No cap on how strongly a light tints.
- His verdict so far on the fighter: ours was weak and soft; Clipdrop's Relight was better but "not good enough either". He has not yet judged the rebuilt rim light or the GPU renders.
- **Keep the handoff complete** (late 2026-10-08): change log, this file, pictures in the handoff folder, and everything pushed, so a session on the other PC can continue.

### What this session did (GPU PC, 2026-10-08)

- **Photoreal render is 4 times faster**: 139 s to 34 s, peak VRAM 4950 to 2268 MB, same picture. Attention slicing was the cause (`models/iclight.py`).
- **Rim light rebuilt** (`shading.rim_field`, shader, `aux_v2.png`). Before: an even glow around every depth edge. Now: the edge that faces the light, or every edge for a light behind the subject; on the subject's visible outline, from the mask; subject only. See `docs/ARCHITECTURE.md` ("Rim light") and `handoff/results/2026-10-08-gpu-pc/cameraman-rim-old-new-photoreal.jpg`.
- **First GPU measurements**: recorded in `docs/ARCHITECTURE.md`. Parity passes on this PC.
- **Cast shadows: started on a branch, not merged** (below).

### Honest reading of the pictures so far

- Fighter, first GPU render: the result is close to the preview's own shading, as on the laptop. The hard diagonal edge on the wall, the dotted floor shadow, and the blue-grey shorts are all there at full size too. So the softness was not just the laptop's small render.
- Cameraman, rim light: in the **preview** the new rim reads as light on an edge, on the correct side. It is still one smooth band; it does not follow the form (broad on a shoulder, thin on hair). A light directly behind lights the whole outline, the camera included, and that can still look like an outline drawn around him.
- Cameraman, **photoreal**: worse than the preview for rims. The orange rim comes out dim and muddy, and a blue rim nearly white. The raw model output ignores the rim and invents a shadow on the wall.

### The work list, in order

1. **Show the user the cameraman pictures and get his verdict on the rim.** He judges by the look. Ask what he wants different: width, brightness, which edges.
2. **Rim light through the photoreal pass.** `add_preview_detail` bounds the fine light to 2.5 times (`DETAIL_LIMIT`); a rim on dark hair needs more. At 8 the orange rim came back on the cameraman (one photo, one try). Check the fighter for noise before changing the default. The blue rim turning white is a colour problem, not a limit problem: look at where `lighting_ratio` takes colour from when the light is only a thin band (the smoothing spreads it thin, so the "share of light" may fall under `LIGHT_SHARE_LOW`).
3. **Rim that follows the form.** Ideas, untested: scale the band's width by how thick the shape is there (distance to the far outline); let the surface normals shape the falloff inside the band; a per-light rim amount in the panel.
4. **Clean cast shadows: finish the branch `wip/shadow-march`.** What is on it (Python only, commit message has the detail): the march reads blurred copies (mip levels) of the height map as wide as each step, so no dotted edges; short steps near the lit point, long ones far away; and the subject is kept apart from the background and given a thickness from the mask, so it no longer shadows everything behind it as if it reached back to the horizon. Seen on the fighter: dotted edge and hard diagonal gone (`handoff/results/2026-10-08-gpu-pc/fighter-shadows-main-vs-wip-branch.jpg`). Open on it:
   - the shadow that is left is soft and faint; sharper settings (`SHADOW_LOD_SCALE` 1 to 1.5, `SHADOW_SPREAD` 0.15, 64 steps) bring back a faint mesh pattern;
   - the shader is not ported: it needs a float texture with mip levels built on the CPU (same averaging as `march_levels`), the constants in `lighting.ts`, tests, and a subject in the parity fixture;
   - **it clashes with `main` over `aux_v2.png`**: the branch put a thickness code in blue, `main` now has the rim map in blue and alpha. When resuming, rebase onto `main` and carry the thickness another way (a third file, or pack it with the mask).
5. **Spotlight cone edge** on the fighter's wall. Most of the hard diagonal turned out to be a shadow edge, not the cone (it goes away on the shadow branch). Check again after step 4.
6. **Visible light shaft (haze)** for spotlights, in the shader and in the hint. A large part of why his reference picture looks dramatic. Per-light setting, default off or low.
7. **Decide what the AI model is still for.** With the fine light from the preview, the model adds only broad realism, and its repainting still leaks (blue-grey shorts, weakened rims). Try a tighter `BRIGHTNESS_LEASH`, a higher "Follow lights", and the preview alone. Show the user the versions side by side and let him pick; this is taste.
8. **A prompt written from the lights** in place of the fixed "beautiful lighting, natural", if step 7 keeps the model. (The user typed his own prompt, "harsh, intense, cinematic", in the app.)
9. **Data folder not carried over on rename.** On the GPU PC `%APPDATA%\Relight` was not renamed to `%APPDATA%\Dope Light`; the app made a new folder and began downloading the models again. The models were copied across by hand that day. `app/src/main/migrate.ts` only renames when the new folder does not exist; something created it first (likely Electron itself, on `app.getPath('userData')` or at startup). It was never tested for real on the laptop, where Claude shells set `RELIGHT_DATA_DIR`. Low priority now (both PCs have the new folder), but it is a real bug for anyone with the old folder.

Be honest with the user about the ceiling: a free model that fits 6 GB will not equal a large cloud generator, and with no redrawing allowed, the look depends on the estimated depth, normals and mask being right.

### Phases

Phases 0 to 4 are built and have now run on the RTX 4050. Phase 4 is still being tuned for the look (above), and the user has not accepted it. **Do not start Phase 5 until he says "go".**

- **Phase 5** on his "go": first-run setup (Python environment, model downloads with progress), settings, project save/load, glass UI polish, a bundled font. Details in `docs/PLAN.md`.
- **Phase 6** after that: installer, auto-update, GitHub releases. It needs Phase 5's first-run setup first, because a packaged app has no Python environment.

Open question for later: the project file extension (`.relight` in the brief) should probably be `.dopelight`; ask when Phase 5 reaches it.

### Lessons already paid for (do not relearn)

- Measure the lighting ratio between *smoothed* pictures, never pixel by pixel: dark areas turn to blotches.
- The model repaints (black shorts became pale cloth). Keep its brightness on a leash to the preview's, take colour from the user's lights where they land, and take only the subject from the model; the background gets the preview's light.
- The dark-surface floor `ALBEDO_FLOOR` stays small (0.02); at 0.06 a strong spot turned black cloth grey.
- Placement matters as much as code: a top spot in front of the subject throws wing-shaped shadows on the wall; directly overhead (depth about equal to the subject's) the shadow falls on the floor.
- A dark photo shows faults a bright portrait hides. Test on both.
- Attention slicing does not save memory with PyTorch 2's attention: at 768 x 1152 it filled the 6 GB card and made each step 8 times slower. It is kept only for the out-of-memory retry.
- Averaging a height map to blur it makes a low wall around every shape, which then casts its own shadow. Keep the subject and the background in separate, weighted channels (the shadow branch does).
- In the relief the floor is a steep ramp, not a flat plane: a light at the top of the picture is not overhead in the room's terms, and shadows land where the relief says, which is not always where the eye expects.
- The depth map's outline sits a few pixels inside the visible one. Anything that must line up with the visible edge (a rim) has to come from the mask.
- Two processes rendering on the 6 GB card at once ruin both the speed and the measurement. Ask the user whether the app is rendering before starting a GPU run.

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
- **PyTorch build:** extras `cpu` and `cu126` in `backend/pyproject.toml`, mutually exclusive. `cu126` chosen for the RTX 4050 (works with older drivers than `cu130`); it runs there (PyTorch 2.14.1+cu126).
- **App name: Dope Light** (the user's decision, 2026-10-08; "Relight" was the brief's working title). Set in `APP_NAME` in `app/src/shared/constants.ts` and `backend/relight_backend/constants.py`, `<title>` in `app/src/renderer/index.html`, `productName` in `app/package.json`. Internal identifiers keep the old word on purpose: the Python package `relight_backend`, the `RELIGHT_*` environment variables. The data folder is `%APPDATA%\Dope Light`; an existing `%APPDATA%\Relight` is renamed to it on first start (`app/src/main/migrate.ts`, `utils/paths.py`) so models are not downloaded again.
- **Logo:** the user's design, redrawn as vector in `app/resources/logo.svg` (a D lit by a cone of light, gold on dark; wordmark "dope" off-white + "light" amber). `npm run icons` renders `icon.png` and `icon.ico` from it. The UI palette follows the logo at the user's request (2026-10-08): warm near-black, off-white text, amber accent; all colours are variables at the top of `app/src/renderer/src/styles.css`.
- **Releases on GitHub:** the user asked for them on 2026-10-08. That is Phase 6 (NSIS installer, auto-update, release workflow) and needs Phase 5's first-run setup first (a packaged app has no Python environment yet: bundle `uv`, create the venv in the data folder, download models with a progress screen).
- **Backend launch:** Electron main picks a free port, makes a random token, spawns the venv Python. Token goes through env var `RELIGHT_TOKEN`. All endpoints need `Authorization: Bearer <token>`.
- **No orphans:** backend gets `--parent-pid` and waits on that process handle; plus `taskkill /T /F` on normal quit. (Phase 0 used "exit when stdin closes". That broke once PyTorch was installed: on Windows a thread blocked reading the stdin pipe made `import torch` hang in another thread, so `/health` never answered. Do not go back to stdin watching.)
- **Lazy heavy imports:** `main.py` must not import torch/transformers at module level; jobs import them. `models/specs.py` is pure data for the same reason.
- **Models (pinned in `models/specs.py`):** mask BiRefNet lite; depth Depth Anything V2 Small; normals DSINE (default), StableNormal turbo, or depth-derived.
- **Map conventions:** depth 16-bit, white = near; normals camera space +X right, +Y up, +Z to viewer; `DEPTH_SCALE = 0.4`. Full table in `docs/ARCHITECTURE.md`. Phase 2 shader must match.
- **Helper map `aux_v2.png`** (RGBA): red = where lights reach, green = square root of large-scale brightness, blue and alpha = the rim map (`128 + 127 × value`). Made at preprocess; a session that only has the old `aux.png` is preprocessed again on its next open (quick, no model runs). A new kind of data in it means a new file name, so old sessions are rebuilt.
- **DSINE quirks:** raw output has X pointing left (wrapper flips it). Its encoder library `geffnet` tries to download ImageNet weights at construction; the wrapper forces `pretrained=False`. Its repo zip is 168 MB of PDFs/GIFs, so only 3 source files are fetched.
- **StableNormal quirks:** code targets diffusers 0.28; the wrapper aliases `diffusers.models.controlnet` to its new location. X also flipped. Only the turbo (one-step YOSO v0.3) variant is used; the full two-stage model is too big for 6 GB.
- **Downloads:** separate process (`utils/fetch_weights.py`) so cancel = kill; `HF_HUB_DISABLE_XET=1` there because the Xet transfer path does not report progress through the progress-bar hook. Server runs with `HF_HUB_OFFLINE=1`.
- **Shading (Phase 2):** formulas and the departures from the brief are in `docs/ARCHITECTURE.md` (`Live preview`). Shader in `app/src/renderer/src/gl/shader.ts`, Python twin in `backend/relight_backend/pipeline/shading.py`; numbers shared through `SHADING` in `app/src/shared/lighting.ts` and guarded by `tests/test_shading.py`. Change both sides together and run `npm run parity`.
- **Preview details:** raw WebGL2 (no Three.js). Depth goes to the GPU as float from `/session/{id}/depth_raw` (16-bit PNGs lose precision in browsers). Bitmaps are decoded with colour management off. `gl.finish()` does not wait in Chromium; timing uses a 1-pixel `readPixels`. Dragging renders at reduced resolution when a full frame exceeds 14 ms.
- **Lights behind the surface (user asked 2026-10-08 to move lights in front of and behind the subject):** a light whose `z` is below the surface under it switches its shadows from solid shapes to 0.15-thick shells, judged from a dilated depth channel; details in `docs/ARCHITECTURE.md`. The slider is labelled Depth; the gizmo turns dashed when behind.
- **Rim light (rebuilt 2026-10-08 on the GPU PC):** from a rim map made at preprocess out of the subject mask, not from depth edges in the app. An edge is lit when it faces the light or the light is behind; never from a light in front. To place one: put the light beside or behind the subject and lower Depth to the subject's own depth or below. Numbers: `RIM_*` in `shading.py`, the three the shader needs also in `SHADING`.
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
- On the target PC the sandbox problem above does not show up: setup, checks, parity, and GPU renders (`scripts/render_scene.py`) all ran from a Claude shell on 2026-10-08 with no extra environment variables, reading and writing the real `%APPDATA%\Dope Light`. Long jobs there: start with `Start-Process` and a log file, then wait on the log.
- The user often has the app open while a Claude session works. The app holds the GPU and its own copy of the backend code: do not start a GPU render while his is running, and tell him to restart the app after backend changes.
- uv is not on PATH in Claude shells on the build machine: `%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`.
- Background commands from Claude are killed after 10 minutes; start long jobs (bench, big downloads) with `Start-Process` and poll the log.
- StableNormal turbo needs ~7 GB RAM on CPU; with 16 GB and other apps open this machine swaps.
- `gh` (GitHub CLI) is not installed; needed in Phase 6 or the user creates the repo by hand.
- Renderer bundle is ~650 kB unsplit; fine for a local app.

## Verify on target PC (not possible here)

- Done 2026-10-07: `npm run setup` picks `cu126` and PyTorch sees the GPU; `npm run bench` peak VRAM per model under 5.5 GB; half-precision sheets look right.
- Still open: status bar shows the GPU name and free VRAM (needs `npm run dev` on the target PC).
- Phase 4, done 2026-10-08: photoreal render at the default size with the detail pass: 34 to 35 s, peak 2268 MB. The look on the user's photos: not accepted yet (see the work list).
- Phase 4, still open: the same render started from the app, with nothing else on the card (the one app render so far overlapped with a script render: 144 s, not a clean number).
- Phase 3, still open: export a real photo on the target PC and time it (laptop CPU: 20 s relit, 137 s with a shadowed light, 18 MP); place a light layer over the photo with Add in the user's editor and compare with the relit export.
- Phase 2, done 2026-10-08: `npm run parity` passes on the GPU PC (23 scenes, at most 1 level off). Which of the PC's two graphics chips Electron drew with was not checked.
- Phase 2, still open: `npm run ui-smoke` passes; frame times with `RELIGHT_BENCH=1` (laptop Intel graphics: 8 lights with shadows 47 ms at 1080p); dragging feels smooth on a 4K photo.

## Rules carried from the brief

The full list is in `docs/PLAN.md` ("Working rules", "When to stop and ask the user"). The ones broken most easily:

- Stop at the end of each phase with a manual test list. Commit often, one logical change per commit. No model weights or user images in git.
- Verify model names, licences, and library APIs against real sources before coding against them.
- Never claim a speed or VRAM number that was not measured on the machine it is about.
