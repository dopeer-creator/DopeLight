"""BiRefNet lite: subject mask."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoModelForImageSegmentation

from relight_backend.models import specs
from relight_backend.models.base import Model, to_normalized_tensor
from relight_backend.utils.image_io import FloatArray

INPUT_SIZE = 1024
class BiRefNetLite(Model):
    spec = specs.BIREFNET_LITE

    def load(self, weights: Path, code: Path | None, device: torch.device,
             dtype: torch.dtype) -> None:
        self.device, self.dtype = device, dtype
        # The model class lives in the weights repo itself (pinned revision).
        model = AutoModelForImageSegmentation.from_pretrained(weights, trust_remote_code=True)
        self._model = model.to(device, dtype).eval()

    def infer(self, image: Image.Image) -> FloatArray:
        """Mask in [0, 1], 1.0 = subject."""
        square = image.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
        pixels = to_normalized_tensor(square).to(self.device, self.dtype)
        with torch.inference_mode():
            logits = self._model(pixels)[-1]
            mask = F.interpolate(
                logits.float().sigmoid(),
                size=(image.height, image.width),
                mode="bilinear",
                align_corners=False,
            )
        return mask[0, 0].clamp(0.0, 1.0).cpu().numpy().astype(np.float32)
