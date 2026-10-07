"""Shared shape for model wrappers: load / infer / unload."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import torch
from PIL import Image

from relight_backend.models.specs import ModelSpec
from relight_backend.utils.device import release_memory
from relight_backend.utils.image_io import FloatArray

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def to_normalized_tensor(image: Image.Image) -> torch.Tensor:
    """RGB image to a (1, 3, H, W) ImageNet-normalized float tensor."""
    mean = np.array(IMAGENET_MEAN, dtype=np.float32)
    std = np.array(IMAGENET_STD, dtype=np.float32)
    pixels = np.asarray(image, dtype=np.float32) / 255.0
    normalized = ((pixels - mean) / std).astype(np.float32)
    return torch.from_numpy(normalized).permute(2, 0, 1)[None]


class Model(ABC):
    spec: ClassVar[ModelSpec]

    def __init__(self) -> None:
        self._model: Any = None
        self.device = torch.device("cpu")
        self.dtype = torch.float32

    @abstractmethod
    def load(self, weights: Path, code: Path | None, device: torch.device,
             dtype: torch.dtype) -> None:
        """Read weights from disk and move the model to `device`."""

    @abstractmethod
    def infer(self, image: Image.Image) -> FloatArray:
        """Return a float32 map at the image's size, in the app's conventions."""

    def unload(self) -> None:
        self._model = None
        release_memory()
