# Results, for the handoff between the two PCs

Pictures this app produced, kept so a session on the other PC can see what the last one saw. One folder per session. They are made from the user's test photos (other people's images), so the same rule applies as for `handoff/pictures/`: not for use anywhere else, and removed when the user says so.

Add a folder and a table here when a session produces pictures worth judging. Keep them small (JPEG, a few hundred kB each).

## `2026-10-08-gpu-pc/` — first session on the RTX 4050

| File | What it shows | What to take from it |
| --- | --- | --- |
| `fighter-first-gpu-render-sheet.jpg` | The fighter scene (yellow top spot, red trim) rendered on the GPU at default settings. Left to right: original, preview shading, raw AI output, result. | The result is close to the preview shading. Faults visible at full size: a hard diagonal edge on the back wall, a dotted shadow edge on the floor, blue-grey shorts. The raw AI output is a full repaint and is never shown as it is. |
| `fighter-shadows-main-vs-wip-branch.jpg` | The fighter's preview shading: `main` (left) and the branch `wip/shadow-march` (right). | On the branch the dotted edge and the hard diagonal are gone, and the wall is no longer in a false shadow. The cast shadow that is left is soft and faint. Branch is Python only; see the work list in `CLAUDE.md`. |
| `cameraman-rim-old-new-photoreal.jpg` | One orange light behind the cameraman, to the right (`docs/scenes/cameraman-orange-rim.json`). Left: the old rim (preview). Middle: the rebuilt rim (preview). Right: the rebuilt rim after the photoreal pass. | Old: an outline of even strength around everything, background objects included. New preview: light on his edge, strongest toward the light, on his real outline. Photoreal: the same rim, but dimmer and muddier. |
| `cameraman-two-rims-and-side-light.jpg` | Left: orange rim from the right plus a blue light from behind left, preview. Middle: the same after the photoreal pass. Right: a single orange light level with him, far right (a side light), preview. | The photoreal pass turns the blue rim nearly white and loses most of the orange. The side light rims only the edges that face it. |
| `cameraman-orange-rim-sheet.jpg` | The full four-panel sheet of the orange rim render (original, preview shading, raw AI output, result). 34.6 s, 2268 MB peak VRAM. | The raw AI output ignores the rim and invents a shadow of the man on the wall. |
