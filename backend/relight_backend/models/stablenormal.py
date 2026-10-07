"""StableNormal turbo (YOSO one-step): surface normals from a diffusion model."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from relight_backend.models import specs
from relight_backend.models.base import Model
from relight_backend.utils.image_io import FloatArray, normalize_vectors, resize_map

# Long edge the diffusion model runs at (rounded to a multiple of 64).
PROCESS_LONG_EDGE = 1024

# The model outputs (X left, Y up, Z toward the viewer); flip X.
# Measured against depth-derived normals (see the benchmark's axis check).
STABLENORMAL_TO_APP = np.array([-1.0, 1.0, 1.0], dtype=np.float32)


def _process_size(image: Image.Image) -> tuple[int, int]:
    scale = PROCESS_LONG_EDGE / max(image.size)
    return (
        max(64, round(image.width * scale / 64.0) * 64),
        max(64, round(image.height * scale / 64.0) * 64),
    )


class StableNormalTurbo(Model):
    spec = specs.STABLENORMAL_TURBO

    def load(self, weights: Path, code: Path | None, device: torch.device,
             dtype: torch.dtype) -> None:
        self.device, self.dtype = device, dtype
        if code is None:
            raise ValueError("StableNormal needs its source code folder")
        if str(code) not in sys.path:
            sys.path.append(str(code))
        # The model's code was written for diffusers 0.28, where this module
        # lived one level up. Point the old name at the new location.
        import diffusers.models.controlnets.controlnet as controlnet_module

        sys.modules.setdefault("diffusers.models.controlnet", controlnet_module)
        from stablenormal.pipeline_yoso_normal import (
            YOSONormalsPipeline,
        )

        pipe = YOSONormalsPipeline.from_pretrained(
            weights,
            variant="fp16",
            dtype=dtype,
            trust_remote_code=True,
            safety_checker=None,
            t_start=0,
            local_files_only=True,
        )
        self._model = pipe.to(device)

    def infer(self, image: Image.Image) -> FloatArray:
        """Unit normals, camera space: +X right, +Y up, +Z toward the viewer."""
        resized = image.resize(_process_size(image), Image.Resampling.LANCZOS)
        with torch.inference_mode():
            output = self._model(resized, match_input_resolution=True)
        raw = np.asarray(output.prediction[0], dtype=np.float32)
        full = resize_map(raw, (image.width, image.height))
        return normalize_vectors(full * STABLENORMAL_TO_APP)
