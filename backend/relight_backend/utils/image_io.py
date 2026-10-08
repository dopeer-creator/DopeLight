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
from typing import Any

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


# OpenCV's own imread/imwrite cannot open paths with non-ASCII characters on
# Windows (a user name is enough), so files go through Python and OpenCV only
# encodes and decodes bytes.
def _write(path: Path, extension: str, data: np.ndarray[Any, Any], params: list[int]) -> None:
    ok, encoded = cv2.imencode(extension, data, params)
    if not ok:
        raise OSError(f"Could not encode {path}")
    path.write_bytes(encoded.tobytes())


def _read_unchanged(path: Path) -> np.ndarray[Any, Any]:
    data = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if data is None:
        raise OSError(f"Could not read {path}")
    return data


def save_gray16(array: FloatArray, path: Path) -> None:
    _write(path, ".png", np.clip(array * 65535.0 + 0.5, 0, 65535).astype(np.uint16), [])


def load_gray16(path: Path) -> FloatArray:
    return np.asarray(_read_unchanged(path), dtype=np.float32) / 65535.0


def save_image(
    array: np.ndarray[Any, Any], path: Path, file_format: str, quality: int = 92
) -> None:
    """Write RGB or RGBA, uint8 or uint16, as "png", "jpeg" (8-bit RGB only) or "tiff"."""
    channels = array.shape[2]
    if file_format == "jpeg" and (array.dtype != np.uint8 or channels != 3):
        raise ValueError("JPEG holds 8-bit RGB only")
    ordered = cv2.cvtColor(array, cv2.COLOR_RGBA2BGRA if channels == 4 else cv2.COLOR_RGB2BGR)
    if file_format == "jpeg":
        # 4:4:4 chroma: no colour smearing on thin light edges.
        params = [cv2.IMWRITE_JPEG_QUALITY, quality,
                  cv2.IMWRITE_JPEG_SAMPLING_FACTOR, cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444]
        _write(path, ".jpg", ordered, params)
    elif file_format == "tiff":
        _write(path, ".tif", ordered, [cv2.IMWRITE_TIFF_COMPRESSION, 5])  # 5 = LZW, lossless
    elif file_format == "png":
        _write(path, ".png", ordered, [])
    else:
        raise ValueError(f"Unknown format {file_format!r}")


def load_image_array(path: Path) -> np.ndarray[Any, Any]:
    """Read a file written by save_image back as RGB(A), keeping its bit depth."""
    data = _read_unchanged(path)
    return cv2.cvtColor(data, cv2.COLOR_BGRA2RGBA if data.shape[2] == 4 else cv2.COLOR_BGR2RGB)


def load_gray16_bytes(path: Path) -> bytes:
    """The 16-bit values as raw little-endian uint16, row by row."""
    data = _read_unchanged(path)
    if data.dtype != np.uint16:
        raise OSError(f"Not a 16-bit image: {path}")
    return data.astype("<u2").tobytes()


def save_normals(normals: FloatArray, path: Path) -> None:
    data = np.clip((normals * 0.5 + 0.5) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(data, mode="RGB").save(path)


def load_normals(path: Path) -> FloatArray:
    data = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    return normalize_vectors(data / 255.0 * 2.0 - 1.0)
