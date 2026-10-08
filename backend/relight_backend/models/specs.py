"""What each model is and where its files come from.

Pure data: importing this never loads PyTorch, so the server can report model
availability right at startup. Revisions are pinned so the code and weights
cannot change underneath the app.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HfWeights:
    """Files from a Hugging Face repo, pinned to an exact revision."""

    repo_id: str
    revision: str
    allow_patterns: tuple[str, ...] = ()  # empty = whole repo


@dataclass(frozen=True)
class GithubCode:
    """Model source files from GitHub, pinned to an exact commit."""

    repo: str
    commit: str
    files: tuple[str, ...]  # only these are fetched; repos carry large extras


@dataclass(frozen=True)
class ModelSpec:
    key: str
    title: str
    license: str
    commercial_use: bool
    approx_size_mb: int
    weights: HfWeights
    code: GithubCode | None = None


DEPTH_ANYTHING_V2_SMALL = ModelSpec(
    key="depth_anything_v2_small",
    title="Depth Anything V2 Small",
    license="Apache-2.0",
    commercial_use=True,
    approx_size_mb=95,
    weights=HfWeights(
        repo_id="depth-anything/Depth-Anything-V2-Small-hf",
        revision="5426e4f0f36572d16453bbda7a8389317b1bef99",
    ),
)

BIREFNET_LITE = ModelSpec(
    key="birefnet_lite",
    title="BiRefNet lite",
    license="MIT",
    commercial_use=True,
    approx_size_mb=170,
    weights=HfWeights(
        repo_id="ZhengPeng7/BiRefNet_lite",
        revision="aa62cd87eafb9cc43056d08ef3615a14628b831d",
    ),
)

DSINE = ModelSpec(
    key="dsine",
    title="DSINE",
    license="Imperial College London non-commercial research licence",
    commercial_use=False,
    approx_size_mb=280,
    weights=HfWeights(
        repo_id="camenduru/DSINE",
        revision="eb7c7991e19351cef4ead99811fc1117595b6bff",
        allow_patterns=("dsine.pt",),
    ),
    code=GithubCode(
        repo="hugoycj/DSINE-hub",
        commit="a6b7d253d515f57404002da58f0c61e90d0387a3",
        files=("models/dsine.py", "models/submodules.py", "utils/rotation.py", "LICENSE"),
    ),
)

STABLENORMAL_TURBO = ModelSpec(
    key="stablenormal_turbo",
    title="StableNormal turbo",
    license="Apache-2.0",
    commercial_use=True,
    approx_size_mb=3200,
    weights=HfWeights(
        repo_id="Stable-X/yoso-normal-v0-3",
        revision="2202fcb69960d94b437e06c19c556a12ceeb57c0",
    ),
    code=GithubCode(
        repo="Stable-X/StableNormal",
        commit="594b934630ab3bc71f35c77d14ec7feb98480cd0",
        files=(
            "stablenormal/__init__.py",
            "stablenormal/pipeline_yoso_normal.py",
            "LICENSE.txt",
        ),
    ),
)

# The photoreal pass: IC-Light is a set of weight offsets on top of a Stable
# Diffusion 1.5 model. Realistic Vision 5.1 is the base IC-Light's own demo uses.
SD15_REALISTIC = ModelSpec(
    key="sd15_realistic_vision",
    title="Realistic Vision 5.1 (Stable Diffusion 1.5)",
    license="CreativeML OpenRAIL-M",
    commercial_use=True,
    approx_size_mb=2040,
    weights=HfWeights(
        repo_id="stablediffusionapi/realistic-vision-v51",
        revision="19e3643d7d963c156d01537188ec08f0b79a514a",
        allow_patterns=(
            "model_index.json",
            "tokenizer/*",
            "text_encoder/config.json",
            "text_encoder/model.safetensors",
            "unet/config.json",
            "unet/diffusion_pytorch_model.safetensors",
            "vae/config.json",
            "vae/diffusion_pytorch_model.safetensors",
        ),
    ),
)

IC_LIGHT_FC = ModelSpec(
    key="ic_light_fc",
    title="IC-Light",
    license="Apache-2.0",
    commercial_use=True,
    approx_size_mb=1640,
    weights=HfWeights(
        repo_id="lllyasviel/ic-light",
        revision="9cad1878695f546a7fb9eaca14e2a89131ba5ffe",
        allow_patterns=("iclight_sd15_fc.safetensors",),
    ),
)

PHOTOREAL: tuple[ModelSpec, ...] = (SD15_REALISTIC, IC_LIGHT_FC)

MASK = BIREFNET_LITE
DEPTH = DEPTH_ANYTHING_V2_SMALL

# Ways to get surface normals. "depth" needs no model of its own.
NORMALS: dict[str, ModelSpec | None] = {
    "dsine": DSINE,
    "stablenormal": STABLENORMAL_TURBO,
    "depth": None,
}
DEFAULT_NORMALS = "dsine"

ALL: tuple[ModelSpec, ...] = (MASK, DEPTH, DSINE, STABLENORMAL_TURBO, *PHOTOREAL)
BY_KEY: dict[str, ModelSpec] = {spec.key: spec for spec in ALL}


def specs_for(normals: str) -> list[ModelSpec]:
    """Models a preprocess run needs for the given normals method."""
    extra = NORMALS[normals]
    return [MASK, DEPTH] + ([extra] if extra else [])
