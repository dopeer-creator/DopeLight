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
| `GET /session/{id}/{map}` | PNG; map is `albedo_proxy`, `normal`, `normal_smooth`, `depth`, `mask`, or `aux` |
| `GET /session/{id}/depth_raw` | depth as raw little-endian uint16, row by row at working size. The preview uses this: browsers decode 16-bit PNGs to 8 bits, which would band the heightfield |
| `POST /session/{id}/export` | JSON: `lights`, `globals`, `kind` (`relit`, `light_layer`, `per_light`), `format` (`png`, `jpeg`, `tiff`), `bit_depth` (8, 16), `quality`, `blend` (`normal`, `linear`), `alpha`, `target` (full path of the main file). Renders at full resolution and writes the files; returns `job_id`; the job's result lists the files |
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

## Export (Phase 3)

`pipeline/export.py`, behind `POST /session/{id}/export`. The backend does the rendering, not an off-screen WebGL pass: it has no texture-size limit, writes 16-bit files, and uses the same `shading.py` the shader is checked against.

How it renders: the original file is the albedo at full size; normals and depth are scaled up to it (bilinear); the two maps derived from depth (top-nearby and outline) are made at the working size and scaled up too, as the preview does. Shading runs a strip of about one megapixel of rows at a time, so memory stays bounded; a strip gives exactly the pixels a single pass would (tested). Shadows use 48 steps instead of the preview's 24. If the GPU runs out of memory it retries on the CPU.

What it writes (the original keeps its name; exports get a suffix):

| Choice | Files | Content |
| --- | --- | --- |
| Relit image | `name_relit` | the finished picture |
| Light layer | `name_light` | what the lights add, on black |
| One layer per light | `name_lights_1_Key`, `_2_Rim`, ... | the light layer split by light; they add up to it exactly |
| + transparent version | `..._alpha` (PNG or TIFF) | the same layer with straight alpha (alpha = brightest channel), for editors without an Add blend |
| (automatic) | `..._base` | only when Original light, Ambient, or Exposure is not at its default: the photo with those settings and no lights. The layers belong on top of this, not the untouched photo |

Formats: PNG 8/16-bit, JPEG (quality, 4:4:4 colour), TIFF 8/16-bit (LZW). The file chosen in the save dialog is replaced (the dialog asks); every other file gets ` (2)`, ` (3)` rather than replacing something.

**The promise: base + layer = relit, with the Add (Linear Dodge) blend mode.** Editors disagree on what Add means, so there are two targets:

- **Photoshop, Affinity, Krita** (default): their Add works on the stored, gamma-encoded values. The layer is `encode(relit) − encode(base)`.
- **GIMP, 32-bit documents**: Add in linear light. The layer is `encode(relit − base)`.

Checked numerically in `tests/test_export.py`: with 16-bit files, base + layer matches the relit export within 3 of 65535 levels for the first target, and within 0.0005 in linear light for the second; per-light layers sum to the light layer within one level per light. A layer can only add light. Because the layer is the exact difference, it also carries the soft clip: its colours can look odd where a channel is near white.

The brief asked for alpha = luminance; brightest channel is used instead, because with luminance a saturated blue or red light would need colour values above 1.

Speed on the build laptop (CPU, 3840 × 4800 portrait): relit with one light 20 s; with one shadowed light 137 s; two 16-bit per-light layers 41 s. **Not yet measured on the RTX 4050.**

Limits: the original is read as 8-bit sRGB (a 16-bit or wide-gamut original is converted first, and no colour profile is embedded); the photoreal exports (difference and multiply layers from the diffusion result) belong to Phase 4.
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

## Live preview (Phase 2)

The picture is drawn by one WebGL2 fragment shader on a full-screen triangle (`app/src/renderer/src/gl/shader.ts`, driven by `gl/renderer.ts`). Raw WebGL2, not Three.js: one triangle and one shader need no scene graph. The three maps are uploaded once per image; after that sliders and dragging only change uniforms.

`backend/relight_backend/pipeline/shading.py` computes the same picture in PyTorch. It exists for the export and photoreal phases, and as the reference the shader is tested against.

### Lighting model

Space: `x = u`, `y = (1 − v) × aspect` (up), `z = DEPTH_SCALE × depth` (toward the viewer), all in image-width units. Colour math is in linear light: the albedo texture is an sRGB texture (the GPU linearizes on sampling) and the result is encoded back to sRGB at the end.

Per light, with `N` the normal, `L` the unit vector to the light, `V = (0, 0, 1)`:

| Term | Formula |
| --- | --- |
| diffuse | `clamp((N·L + w) / (1 + w), 0, 1)`, `w = diffusion` (wrap lighting; 1 = half-Lambert) |
| falloff (point, spot) | `1 / (1 + (d / r)²)`, `r = radius × (1 + diffusion)` |
| cone (spot) | `smoothstep(cos(angle/2), cos(angle/2 × (1 − softness)), −L·dir)` |
| specular | Blinn-Phong: `specular × (N·H)^shininess`, faded out as `N·L` drops below 0.1 |
| shadow | march from the pixel toward the light over the depth heightfield (24 steps, at most 48), jittered per pixel; the deepest overlap divided by a penumbra width (0.012 to 0.08, growing with diffusion) is the occlusion |
| rim | for a light behind the pixel: `1.5 × smoothstep(0, 0.5, −L.z) × outline²`, where `outline` (0..1) marks the near side of depth edges; not shadowed |
| contribution | `colour × intensity × falloff × cone × (shadow × (albedo × diffuse + specular) + rim × mix(albedo, white, 0.35))` |

Composite: `albedo × (keepOriginalLight + ambient) + Σ contributions`, times `2^exposure`, then a soft clip (unchanged below 0.8, a tanh roll-off above that never passes 1), then sRGB. With no lights and default settings the picture is the original, except that highlights above 0.8 linear are rolled off slightly.

Where this departs from the brief's wording:

- **Aim point instead of a direction vector.** Spot and directional lights store a `target` (x, y on the image); the direction is from the light to that point at half the relief height. It gives one draggable handle instead of a 3-D direction widget.
- **Depth of a light** (`z`; the brief calls it height) is measured from the image plane (`z = 0`, the farthest depth) toward the viewer. The photo's relief reaches up to `z = 0.4`, so a light with a lower `z` than the surface under it is **behind** that surface. The gizmo turns dashed and the panel says so.
- **Ambient and "original light" add up** to one base factor, because the albedo is still the photo itself (v1 has no intrinsic decomposition). They become different once a real albedo exists.
- **Preview sharpness** is limited by the working size (long edge 1536 px): the albedo texture is the albedo proxy, not the full-resolution file. Full resolution is for export (Phase 3).

### Fixes for how the preview looked (2026-10-08)

The user's first real test (a bright outdoor game screenshot) looked wrong in four ways. Each got a fix, in both the shader and `shading.py`:

| Fault | Fix |
| --- | --- |
| The sky was lit like a wall | **Reach map.** The depth model predicts inverse depth: sky reads 0, the farthest indoor wall still reads 7 to 8 % of the nearest point (measured on the samples). Pixels below 0.4 % get no light at all, fading in up to 2 %. Light contributions are multiplied by it |
| Wet, plastic-looking highlights | New lights have **specular 0**. The slider remains |
| Blocky patches, noise, false bumps | **Smooth surface** (scene setting, default 0.3): normals lean toward a blurred copy (Gaussian, 0.6 % of the width) made at preprocess time |
| Bright photos blew out, and new light just multiplied old light | **Even light** (scene setting, default 0.5): lights act on the photo's colours scaled by `(0.18 / brightness)^amount` (capped at 4), where `brightness` is the photo's luminance blurred by 4 % of the width. Bright regions take less new light, dark ones more. This is the brief's optional shading flattening; the base image is not changed |

Preprocess writes the helper maps: `normal_smooth_<method>.png`, `reach.png` (kept beside the depth), and `aux.png` (red = reach, green = square root of brightness), which the app loads as two more textures. Sessions made before this get them on the next open (the depth model runs again, about 2 s on CPU).

### Lights behind the surface

A depth map only describes the visible front of things. Shadows normally treat every shape as a solid reaching all the way back, which is the safe guess for a light in front. A light placed behind a shape would then be buried inside a solid and light nothing.

So each light gets an *embed* value: the surface height at the light's own spot minus the light's `z` (for a directional light: +1000 if it shines from the back, −1000 otherwise). When it is positive the light is behind the surface, and for that light:

- shapes count as **shells** at most 0.15 thick (and never thicker than 70 % of the embed depth, so the light itself stays outside the shell);
- a ray is blocked only while it is inside a shell. Light can travel in the gap between a subject and the backdrop, so the backdrop glows around the subject, the subject's front stays dark, and edges facing the light get a rim;
- thickness is counted from the shape's top nearby (a small max filter of the depth map, stored in the depth texture's second channel), not from the steep wall every outline has in a depth map. Without that a ray passing under a shape always hit the wall.

**Rim light.** A backlight in a photo shows mostly as a bright outline. The preview draws it from an *outline map*: for each pixel, how far it stands above the lowest depth within 1, 2, 3, and 4 small steps (each 0.15 % of the image width), averaged. That is 1 right at the near side of a depth edge and fades within a few pixels. It is stored in the depth texture's third channel. Lights in front of a pixel add no rim.

The switch from solid to shell fades in over the first 0.03 of embed depth. This is still a relief, not a 3-D model: there is no far side of anything, and the camera cannot move.

The shader's numbers come from `SHADING` in `app/src/shared/lighting.ts`; `shading.py` holds the same values and `backend/tests/test_shading.py` fails if they drift apart.

### Parity test

`npm run parity` builds a synthetic scene (sloped floor, dome, box), has Electron render 21 light setups with the real shader off screen, renders the same with `shading.py`, and compares the 8-bit results. Limits: mean difference at most 0.5 levels and at most 0.5 % of pixels off by more than 3 levels. Measured on the build laptop (Intel Iris Xe, 2026-10-08): **every scene within 1 level of 255, mean 0.05 to 0.09**, including shadows with jitter, lights behind the surface, and eight mixed lights. Side-by-side images land in `parity-out/`.

### Speed

The shader's cost is per output pixel, so the preview renders at the size the picture is shown at (times the display's pixel ratio), never at the image's full size. While dragging, if a full-quality frame takes longer than 14 ms, frames are drawn at a lower resolution (down to 40 % per side) and the picture sharpens again 250 ms after the last change. The status bar shows the full-quality frame time.

Measured with `RELIGHT_BENCH=1` on the build laptop (Intel Iris Xe integrated graphics, portrait sample):

| Scene | 1920×1080 | 3840×2160 |
| --- | --- | --- |
| 1 light, no shadows | 4.5 ms (223 fps) | 8.8 ms (114 fps) |
| 3 lights, 2 with shadows | 15.1 ms (66 fps) | 51.5 ms (19 fps) |
| 8 lights, all with shadows | 47.3 ms (21 fps) | 153.3 ms (7 fps) |

**Not yet measured on the RTX 4050.** Shadows dominate the cost (24 depth samples per shadowed light per pixel).

### Reference targets

The user's `references/` folder (not committed: third-party images) holds a screenshot of Photoshop's Relight panel and a six-way relit portrait. From them: position sliders Left · Right, Low · High, Close · Far (built, next to dragging); a backlight with a bright rim and dark face (built, see above); and soft, realistic skin shading with deep cast shadows, which the preview only approximates and the photoreal pass (Phase 4) is for.

### Interaction

State lives in three Zustand stores: `sessionStore` (open image, maps, progress), `lightsStore` (lights, scene settings, selection, undo history), `viewStore` (compare, split). Undo works by checkpoints: a snapshot is saved at the start of each gesture (pointer down on a gizmo or slider, a key press, a button), so one drag is one undo step.

`npm run ui-smoke` starts the real app, opens a sample, and runs `scripts/ui-smoke.browser.js` inside the page: it drags a gizmo, turns the wheel, presses the shortcuts, moves a slider, and checks the app's state after each (22 checks).

Development helpers are environment variables read by `app/src/main/dev.ts` (`RELIGHT_OPEN`, `RELIGHT_SCENE`, `RELIGHT_SCREENSHOT`, `RELIGHT_BENCH`, `RELIGHT_SCRIPT`, `RELIGHT_PARITY`); none work in a packaged app.

### Known limits

- In pure-black parts of a photo the estimated normals are noise, so lights draw blotchy patterns there.
- Shadows come from a heightfield seen from one side: there is nothing behind the visible surface, and depth edges cast hard-edged shadows.
- With a light behind the surface, the lit backdrop can show a fine dotted pattern (the per-pixel jitter of the shadow samples against the hard shell edge).
- A lost WebGL context is not recovered; the app would need a restart.
