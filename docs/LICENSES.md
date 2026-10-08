# Licenses

Relight is for personal use. This file tracks the license of each third-party piece and flags anything that forbids commercial use.

**One model is non-commercial: DSINE.** Everything else allows commercial use. If Relight is ever released or used for paid work, switch normals to StableNormal turbo or depth-derived (both in settings) and remove DSINE.

## Models

Checked on 2026-10-03 against each model's own repository. Nothing here is bundled with the app; weights and model code are downloaded on first use into the app's data folder, pinned to the exact revisions in `backend/relight_backend/models/specs.py`.

| Model | Used for | License | Commercial use | Source |
| --- | --- | --- | --- | --- |
| Depth Anything V2 Small | depth | Apache-2.0 | allowed | [depth-anything/Depth-Anything-V2-Small-hf](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf) |
| BiRefNet lite | subject mask | MIT | allowed | [ZhengPeng7/BiRefNet_lite](https://huggingface.co/ZhengPeng7/BiRefNet_lite) |
| DSINE | surface normals (default) | Imperial College London research licence | **forbidden** | code: [hugoycj/DSINE-hub](https://github.com/hugoycj/DSINE-hub) (the torch-hub build linked from the [official repo](https://github.com/baegwangbin/DSINE)); weights: [camenduru/DSINE](https://huggingface.co/camenduru/DSINE) |
| StableNormal turbo (YOSO v0.3) | surface normals (optional) | Apache-2.0 | allowed | code: [Stable-X/StableNormal](https://github.com/Stable-X/StableNormal); weights: [Stable-X/yoso-normal-v0-3](https://huggingface.co/Stable-X/yoso-normal-v0-3) |
| IC-Light (`fc` weights) | photoreal relight | Apache-2.0 (the [IC-Light repository](https://github.com/lllyasviel/IC-Light); the weights page states no licence of its own) | allowed | [lllyasviel/ic-light](https://huggingface.co/lllyasviel/ic-light) |
| Realistic Vision 5.1 (Stable Diffusion 1.5) | base model IC-Light is applied to | CreativeML OpenRAIL-M | allowed, with the licence's use restrictions (no illegal or harmful use; the same terms must be passed on if the model is redistributed) | [stablediffusionapi/realistic-vision-v51](https://huggingface.co/stablediffusionapi/realistic-vision-v51) |

### DSINE licence, in plain words

The licence text (kept next to the downloaded code as `LICENSE`) says the software may be used "solely for non-commercial, internal or academic research purposes". It also forbids passing it on to others, so Relight must never ship DSINE's code or weights inside an installer. Downloading it to your own PC for your own non-commercial use is what the licence permits.

The DSINE weights file is a PyTorch pickle from a third-party mirror. It is loaded with `weights_only=True`, which refuses to run code hidden in the file.

IC-Light's official demo removes the background with BRIA RMBG 1.4, which is non-commercial. Relight does not use it: the whole photo is relit, and the subject mask comes from BiRefNet (MIT).

### Not used

- Depth Anything V2 Base/Large: non-commercial (CC-BY-NC-4.0), and not needed.
- rembg `isnet-general-use` (Apache-2.0): the brief named it as a mask fallback. BiRefNet lite worked, so no fallback was built.

## Software

| Component | License | Commercial use |
| --- | --- | --- |
| Electron | MIT | allowed |
| React, React DOM | MIT | allowed |
| Vite, electron-vite | MIT | allowed |
| Zustand | MIT | allowed |
| lucide-react | ISC | allowed |
| FastAPI | MIT | allowed |
| Uvicorn | BSD-3-Clause | allowed |
| PyTorch, torchvision | BSD-3-Clause | allowed |
| transformers, diffusers, huggingface-hub, accelerate, safetensors | Apache-2.0 | allowed |
| OpenCV | Apache-2.0 | allowed |
| NumPy | BSD-3-Clause | allowed |
| Pillow | MIT-CMU | allowed |
| timm, kornia, geffnet | Apache-2.0 | allowed |
| einops | MIT | allowed |
| uv | MIT or Apache-2.0 | allowed |

## Sample photos (benchmark only, not committed)

Fetched by `scripts/fetch-samples.mjs` from Wikimedia Commons: a NASA portrait and a US National Park Service landscape (public domain), and a product photo and an interior photo (CC0).
