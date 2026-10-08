"""Depth Anything V2 Small: relative depth."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

from relight_backend.models import specs
from relight_backend.models.base import Model
from relight_backend.utils.image_io import FloatArray

# The model predicts inverse depth: the sky reads 0, the nearest point the
# highest value. Measured on the sample photos, the farthest indoor wall still
# reads 7 to 8 % of the nearest point and a studio backdrop about 2 %, so
# "below a few tenths of a percent" means "infinitely far".
REACH_START = 0.004
REACH_FULL = 0.02


def light_reach(raw: FloatArray) -> FloatArray:
    """1 where a light in the scene can reach, fading to 0 for sky and the far distance."""
    nearest = max(float(np.percentile(raw, 99.5)), 1e-6)
    t = np.clip((raw / nearest - REACH_START) / (REACH_FULL - REACH_START), 0.0, 1.0)
    return np.asarray(t * t * (3.0 - 2.0 * t), dtype=np.float32)


def normalize_depth(raw: FloatArray) -> FloatArray:
    """Scale to [0, 1] using robust percentiles so a few outliers do not flatten the map."""
    low, high = np.percentile(raw, [0.5, 99.5])
    scaled = (raw - low) / max(float(high - low), 1e-6)
    return np.asarray(np.clip(scaled, 0.0, 1.0), dtype=np.float32)


class DepthAnythingV2Small(Model):
    spec = specs.DEPTH_ANYTHING_V2_SMALL

    def load(self, weights: Path, code: Path | None, device: torch.device,
             dtype: torch.dtype) -> None:
        self.device, self.dtype = device, dtype
        self._processor = AutoImageProcessor.from_pretrained(weights)
        model = AutoModelForDepthEstimation.from_pretrained(weights, dtype=dtype)
        self._model = model.to(device).eval()

    def infer(self, image: Image.Image) -> FloatArray:
        """Depth in [0, 1], 1.0 = nearest (the model predicts inverse depth)."""
        inputs = self._processor(images=image, return_tensors="pt")
        pixels = inputs["pixel_values"].to(self.device, self.dtype)
        with torch.inference_mode():
            predicted = self._model(pixel_values=pixels).predicted_depth
            resized = F.interpolate(
                predicted[:, None].float(),
                size=(image.height, image.width),
                mode="bicubic",
                align_corners=False,
            )
        raw = resized[0, 0].cpu().numpy()
        self.extras["reach"] = light_reach(raw)
        return normalize_depth(raw)
