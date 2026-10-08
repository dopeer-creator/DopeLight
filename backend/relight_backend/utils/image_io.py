"""Image loading, resizing, and map encoding.

Conventions (also in docs/ARCHITECTURE.md):
- depth: float32 in [0, 1], 1.0 = nearest to the camera. Saved as 16-bit gray PNG.
- normals: float32 unit vectors in camera space, +X right, +Y up, +Z toward the
  viewer. Saved as 8-bit RGB PNG with rgb = (n * 0.5 + 0.5) * 255.
- mask: float32 in [0, 1], 1.0 = subject. Saved as 8-bit gray PNG.
"""

from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image, ImageOps

FloatArray = npt.NDArray[np.float32]


def load_image(source: Path | bytes) -> Image.Image:
    """Open as RGB with the EXIF rotation applied."""
    opened = Image.open(io.BytesIO(source) if isinstance(source, bytes) else source)
    return ImageOps.exif_transpose(opened).convert("RGB")


def resize_long_edge(image: Image.Image, long_edge: int) -> Image.Image:
    """Downscale so the long edge is at most `long_edge`; never upscale."""
    scale = long_edge / max(image.size)
    if scale >= 1.0:
        return image
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def resize_map(array: FloatArray, size: tuple[int, int]) -> FloatArray:
    """Resize a float map to (width, height)."""
    resized = cv2.resize(array, size, interpolation=cv2.INTER_CUBIC)
    return np.asarray(resized, dtype=np.float32)


def normalize_vectors(vectors: FloatArray) -> FloatArray:
    length = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return np.asarray(vectors / np.maximum(length, 1e-6), dtype=np.float32)


def save_gray8(array: FloatArray, path: Path) -> None:
    data = np.clip(array * 255.0 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(data, mode="L").save(path)


def save_gray16(array: FloatArray, path: Path) -> None:
    data = np.clip(array * 65535.0 + 0.5, 0, 65535).astype(np.uint16)
    if not cv2.imwrite(str(path), data):
        raise OSError(f"Could not write {path}")


def load_gray16(path: Path) -> FloatArray:
    data = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if data is None:
        raise OSError(f"Could not read {path}")
    return np.asarray(data, dtype=np.float32) / 65535.0


def load_gray16_bytes(path: Path) -> bytes:
    """The 16-bit values as raw little-endian uint16, row by row."""
    data = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if data is None or data.dtype != np.uint16:
        raise OSError(f"Could not read 16-bit image {path}")
    return data.astype("<u2").tobytes()


def save_normals(normals: FloatArray, path: Path) -> None:
    data = np.clip((normals * 0.5 + 0.5) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(data, mode="RGB").save(path)


def load_normals(path: Path) -> FloatArray:
    data = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return normalize_vectors(data / 255.0 * 2.0 - 1.0)
