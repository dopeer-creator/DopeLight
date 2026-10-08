# Pictures for the handoff between the two PCs

The user asked on 2026-10-08 for these to be pushed so that the session on the GPU PC has them without any file being copied by hand. **They are other people's images in a public repository, and the user said they will be removed later.** When he says so, delete this folder; note that deleted files stay in the git history unless the history is rewritten, so ask him which he wants.

Do not use these pictures anywhere else (not in the README, not in a release).

| File | What it is | What to take from it |
| --- | --- | --- |
| `fighter.jpg` | The user's test photo: a dark, low-key studio shot (407 x 622). | The photo to relight. Brief: yellow spotlight from the top, red trim spotlight from the right, subject a little darker, cast shadows that read. Scene: `docs/scenes/fighter-yellow-top-red-trim.json`. |
| `fighter-chatgpt-crispness-reference.webp` | ChatGPT's image generator given the same brief. It **redrew** the picture. | **A reference for crispness only.** A visible shaft of light from above, deep shadow on the subject, a red rim, a real cast shadow on the floor. The user does not want redrawing; he wants light this crisp on his own pixels. |
| `fighter-clipdrop.jpg` | Clipdrop's Relight on the same photo (screenshot, browser bar cropped off). | The user: "not good enough either", but better than ours was. Warm light over the whole scene, background included. |
| `photoshop-relight-1.png` to `-5.png` | Photoshop's Relight on an illustration: one blue light, then blue plus red, with the panel visible. | **The target.** "The lighting is very crisp, very accurate." Strong coloured light on the subject and the background, no cap on colour. The panel shows the controls: colour, position sliders, intensity, diffusion, original lighting. |
| `photoshop-relight-panel.jpg` | Photoshop's Relight panel with a light gizmo on a photo. | Layout of the panel and the on-canvas light handle. |
| `photoshop-six-way-portrait.webp` | One portrait under six lighting setups. | The range of looks one photo should reach: side, top, back, under, front. |
| `first-test-relit.webp`, `first-test-light-layer.png`, `first-test-composite.webp` | The user's first real test of this app's Phase 3 export: relit image, light layer, and the two combined in his editor. | His verdict then: "the lighting doesn't look good yet though or accurate". History only; the pipeline has changed since. The relit one can serve as a bright outdoor test photo. |
