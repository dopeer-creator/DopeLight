# Change log

What changed, newest first, in plain words. One entry per working session. The detail of how things work is in `docs/ARCHITECTURE.md`; where the work stands and what is next is in `CLAUDE.md`. Add an entry before ending a session.

## 2026-10-09 — laptop

Continued the work list from the GPU session. Everything here ran on the laptop's CPU; none of it has been run on the RTX 4050 yet.

**Photoreal pass keeps rim lights and colour.** The last step (putting the AI model's light onto the photo) was rebuilt. The result is now the preview's own picture at full size, with the model only scaling its brightness broadly. Rim lights are added exactly as the preview draws them. Fixed by this: rims coming out dim and muddy, a blue rim turning white, and the fighter's black shorts turning blue-grey. Commit `7699ee7`.

**Rim light follows the form.** Before, a rim was a band of one width and one strength around the subject, which read as an outline drawn around a person. Now each part of the subject gets a rounded edge as thick as the part is (broad on a shoulder, a hairline on a finger), and the rim is the light that edge catches: only on the side the light is on, a bright thin line at the outline fading inward, in the light's colour. A light level with the subject gives just the line; a light behind gives the full band. Live preview shader and Python reference changed together; the parity check (23 scenes) and the app smoke test (29 checks) pass.

**Found on the way.** A rim built from a pixel outline shows comb-like stripes along vertical edges unless the edge direction is blurred well. The helper map file is now `aux_v3.png`; photos opened before get it rebuilt on their next open (quick).

**Progress you can read.** While a render or export runs, the dialog now shows the whole status line, a clock, and the bar under it; a model download fills the bar and says it happens only once. Before, the text was cut to `Dow...` and the bar stayed empty for the whole download.

**Pictures.** `handoff/results/2026-10-09-laptop/`.

**Not done.** Cast shadows (branch `wip/shadow-march`), the spotlight edge, the light shaft, and deciding how much the AI model is still needed: with these changes it alters the picture only a little.

## 2026-10-08 — RTX 4050 PC (second session of the day)

First session on the GPU PC after Phases 2 to 4 arrived from the laptop.

**Faster photoreal render.** 139 s down to 34 s, and peak VRAM 4950 MB down to 2268 MB, for the same picture. One memory-saving setting (attention slicing) was doing the opposite on this card at the high-resolution size. Commit `0226526`.

**Rim light rebuilt.** The user could not get a rim light on a person. The old rim was a glow of even strength around every depth edge, whatever the light's position. Now an edge is lit when it faces the light or the light is behind the subject, the rim sits on the subject's visible outline (taken from the mask), and only the subject gets one. Soft lights give a broader rim. Shader and Python reference agree (parity: 23 scenes, at most 1 level off). Commit `4512a1c`.

**Measured on the GPU for the first time.** Photoreal render at default settings: 34 to 35 s, 2268 MB peak. Shader/reference parity passes on this PC. Numbers are in `docs/ARCHITECTURE.md`.

**New test photo.** The user added `handoff/pictures/types-of-shots-in-film.jpg` (a cameraman in a studio) as the next subject. Lighting setups for it: `docs/scenes/cameraman-*.json`.

**Tools.** `scripts/render_scene.py --preview-only` writes just the preview's shading in a second or two, for judging shading changes without the AI model. `scripts/find-uv.mjs` and `scripts/uv.mjs` make the npm scripts work when `uv` is not on PATH.

**Started, not finished: cleaner cast shadows.** On the branch `wip/shadow-march`, Python side only. It removes the dotted shadow edge and the hard diagonal edge on the fighter photo. Not on `main`: the app's shader is not ported, so the two would disagree. Details in `CLAUDE.md`.

**Found, not fixed.**

- The photoreal pass weakens rim lights: dimmer and muddier than the preview, and a blue rim comes out nearly white.
- The rim is one smooth band along the outline. It does not yet follow the form of the body.
- The app's data folder was not carried over from the old name on this PC ("Relight" to "Dope Light"), so the app began downloading the models again. The files were copied across by hand; the cause is not fixed.
- A photo that was opened before this session is preprocessed again the next time it is opened, so its helper map gets the rim. That is quick: no model runs.

**Housekeeping.** Project moved to `C:\Users\Asus\Downloads\DopeLight`, a fresh git repository pushed to GitHub under `Prathamgit9`.

## 2026-10-08 — laptop

Phases 2, 3 and 4 built (live preview, exports, photoreal pass), the app renamed Dope Light with the user's logo and colours, the plan and handoff notes written. See the git history from `4926fba` to `604e412`.

## 2026-10-07 — RTX 4050 PC

Phase 1 benchmark on the GPU: every model under the 5.5 GB limit, highest peak 4326 MB, about 3.5 s per image with the default models.
