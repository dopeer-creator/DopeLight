"""Surface normals derived from the depth map (no extra model needed)."""

from __future__ import annotations

import cv2
import numpy as np

from relight_backend.constants import DEPTH_SCALE
from relight_backend.utils.image_io import FloatArray, normalize_vectors

# cv2.Scharr sums weights 3+10+3 on each side of a 2-pixel span.
_SCHARR_NORM = 32.0


def normals_from_depth(depth: FloatArray, depth_scale: float = DEPTH_SCALE) -> FloatArray:
    """Depth in [0, 1] (1 = near) to camera-space normals (+X right, +Y up, +Z to viewer).

    The surface is z = depth_scale * depth over x, y in image-width units, so a
    one-pixel step is 1 / width.
    """
    width = depth.shape[1]
    smooth = cv2.bilateralFilter(depth.astype(np.float32), d=9, sigmaColor=0.04, sigmaSpace=5)
    to_slope = width * depth_scale / _SCHARR_NORM
    dz_dx = cv2.Scharr(smooth, cv2.CV_32F, 1, 0) * to_slope
    dz_dy_down = cv2.Scharr(smooth, cv2.CV_32F, 0, 1) * to_slope
    # normal = (-dz/dx, -dz/dy_up, 1) and dy_up = -dy_down
    normals = np.stack([-dz_dx, dz_dy_down, np.ones_like(dz_dx)], axis=-1)
    return normalize_vectors(normals.astype(np.float32))
