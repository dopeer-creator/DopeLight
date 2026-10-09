# Results, for the handoff between the two PCs

Pictures this app produced, kept so a session on the other PC can see what the last one saw. One folder per session. They are made from the user's test photos (other people's images), so the same rule applies as for `handoff/pictures/`: not for use anywhere else, and removed when the user says so.

Add a folder and a table here when a session produces pictures worth judging. Keep them small (JPEG, a few hundred kB each).

## `2026-10-09-laptop/` — rim light that follows the form, photoreal pass that keeps it

Each picture has three panels: the preview's shading with the new rim; the photoreal result **before** this session (old rim, old transfer); the photoreal result **now**. Made on the laptop's CPU, AI model at 512 x 320 and 12 steps, so judge the light, not the fine detail.

| File | What it shows | What to take from it |
| --- | --- | --- |
| `cameraman-orange-rim-preview-before-now.jpg` | One orange light behind the cameraman, to the right (`docs/scenes/cameraman-orange-rim.json`). | Before: a yellow line of even width around him and the camera, like a sticker outline. Now: a bright orange line on the side the light is on, fading inward, broader on the shoulder and back than on the ear and hand; nothing on the far side. |
| `cameraman-two-rims-preview-before-now.jpg` | Orange from behind right plus blue from behind left (`cameraman-orange-and-blue-rims.json`). | Before: both rims nearly white. Now: each keeps its colour and its own side. The blue core goes pale where it clips. |
| `fighter-preview-before-now.jpg` | Yellow top spot plus red trim from the right (`fighter-yellow-top-red-trim.json`). | Before: black shorts turned blue-grey, light soft. Now: shorts stay dark, the red trim is a crisp line down his right side, thin highlights on the top edges. Still there: the hard diagonal on the wall and the dotted shadow on the floor (the shadow branch). |

## `2026-10-08-gpu-pc/` — first session on the RTX 4050

| File | What it shows | What to take from it |
| --- | --- | --- |
| `fighter-first-gpu-render-sheet.jpg` | The fighter scene (yellow top spot, red trim) rendered on the GPU at default settings. Left to right: original, preview shading, raw AI output, result. | The result is close to the preview shading. Faults visible at full size: a hard diagonal edge on the back wall, a dotted shadow edge on the floor, blue-grey shorts. The raw AI output is a full repaint and is never shown as it is. |
| `fighter-shadows-main-vs-wip-branch.jpg` | The fighter's preview shading: `main` (left) and the branch `wip/shadow-march` (right). | On the branch the dotted edge and the hard diagonal are gone, and the wall is no longer in a false shadow. The cast shadow that is left is soft and faint. Branch is Python only; see the work list in `CLAUDE.md`. |
| `cameraman-rim-old-new-photoreal.jpg` | One orange light behind the cameraman, to the right (`docs/scenes/cameraman-orange-rim.json`). Left: the old rim (preview). Middle: the rebuilt rim (preview). Right: the rebuilt rim after the photoreal pass. | Old: an outline of even strength around everything, background objects included. New preview: light on his edge, strongest toward the light, on his real outline. Photoreal: the same rim, but dimmer and muddier. |
| `cameraman-two-rims-and-side-light.jpg` | Left: orange rim from the right plus a blue light from behind left, preview. Middle: the same after the photoreal pass. Right: a single orange light level with him, far right (a side light), preview. | The photoreal pass turns the blue rim nearly white and loses most of the orange. The side light rims only the edges that face it. |
| `cameraman-orange-rim-sheet.jpg` | The full four-panel sheet of the orange rim render (original, preview shading, raw AI output, result). 34.6 s, 2268 MB peak VRAM. | The raw AI output ignores the rim and invents a shadow of the man on the wall. |
