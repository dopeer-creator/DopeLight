"""Device and precision choice, and memory release."""

from __future__ import annotations

import gc

import torch


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def pick_dtype(device: torch.device) -> torch.dtype:
    """Half precision on GPU to fit 6 GB VRAM; CPU needs full precision."""
    return torch.float16 if device.type == "cuda" else torch.float32


def release_memory() -> None:
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
