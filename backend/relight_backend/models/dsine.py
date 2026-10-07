"""DSINE: surface normals. Non-commercial licence (Imperial College London)."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import geffnet
import numpy as np
import torch
from PIL import Image

from relight_backend.models import specs
from relight_backend.models.base import Model, to_normalized_tensor
from relight_backend.utils.image_io import FloatArray, normalize_vectors

# The model was trained assuming known camera intrinsics; without them its own
# demo code assumes a 60 degree field of view.
ASSUMED_FOV_DEGREES = 60.0
PAD_MULTIPLE = 32

# This build of DSINE outputs (X left, Y up, Z toward the viewer); flip X.
# Measured against depth-derived normals (see the benchmark's axis check).
DSINE_TO_APP = np.array([-1.0, 1.0, 1.0], dtype=np.float32)


def _padding(height: int, width: int) -> tuple[int, int, int, int]:
    """(left, right, top, bottom) zero padding to reach multiples of 32."""
    pad_w = (-width) % PAD_MULTIPLE
    pad_h = (-height) % PAD_MULTIPLE
    return pad_w // 2, pad_w - pad_w // 2, pad_h // 2, pad_h - pad_h // 2


def _intrinsics(height: int, width: int, device: torch.device) -> torch.Tensor:
    focal = (max(height, width) / 2.0) / math.tan(math.radians(ASSUMED_FOV_DEGREES / 2.0))
    return torch.tensor(
        [[focal, 0.0, width / 2.0 - 0.5], [0.0, focal, height / 2.0 - 0.5], [0.0, 0.0, 1.0]],
        dtype=torch.float32,
        device=device,
    )[None]


def _build_without_pretrained_download(model_class: Any) -> Any:
    """Construct DSINE without fetching ImageNet encoder weights.

    Its encoder asks geffnet for pretrained weights (a ~120 MB download) that
    dsine.pt then overwrites anyway. Skipping it keeps loading fast and offline.
    """
    original = geffnet.create_model

    def create_untrained(name: str, **kwargs: Any) -> Any:
        return original(name, **{**kwargs, "pretrained": False})

    geffnet.create_model = create_untrained
    try:
        return model_class()
    finally:
        geffnet.create_model = original


class Dsine(Model):
    spec = specs.DSINE

    def load(self, weights: Path, code: Path | None, device: torch.device,
             dtype: torch.dtype) -> None:
        # Runs in float32 on every device, as the authors' code does.
        self.device, self.dtype = device, torch.float32
        if code is None:
            raise ValueError("DSINE needs its source code folder")
        if str(code) not in sys.path:
            sys.path.append(str(code))
        from models.dsine import DSINE

        state = torch.load(weights / "dsine.pt", map_location="cpu", weights_only=True)
        model = _build_without_pretrained_download(DSINE)
        model.load_state_dict(state["model"], strict=True)
        model = model.to(device).eval()
        model.pixel_coords = model.pixel_coords.to(device)
        self._model = model

    def infer(self, image: Image.Image) -> FloatArray:
        """Unit normals, camera space: +X right, +Y up, +Z toward the viewer."""
        height, width = image.height, image.width
        left, right, top, bottom = _padding(height, width)
        pixels = to_normalized_tensor(image).to(self.device)
        # Pad with the normalized value of black, matching "pad then normalize".
        black = to_normalized_tensor(Image.new("RGB", (1, 1))).to(self.device)
        padded = black.expand(1, 3, height + top + bottom, width + left + right).clone()
        padded[:, :, top : top + height, left : left + width] = pixels

        intrinsics = _intrinsics(height, width, self.device)
        intrinsics[:, 0, 2] += left
        intrinsics[:, 1, 2] += top

        with torch.inference_mode():
            predicted = self._model(padded, intrins=intrinsics)[-1]
        cropped = predicted[0, :, top : top + height, left : left + width]
        raw = cropped.permute(1, 2, 0).float().cpu().numpy()
        return normalize_vectors(raw * DSINE_TO_APP)
