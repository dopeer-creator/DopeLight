"""GPU detection and VRAM readings.

Tries torch (CUDA) first, then `nvidia-smi`, then reports no GPU. torch is not
installed until the model phases, so the fallbacks matter.
"""

from __future__ import annotations

import importlib
import logging
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import ModuleType

log = logging.getLogger(__name__)

_MB = 1024 * 1024


@dataclass(frozen=True)
class GpuInfo:
    available: bool
    name: str | None
    vram_total_mb: int | None
    vram_free_mb: int | None
    source: str  # "torch" | "nvidia-smi" | "none"


NO_GPU = GpuInfo(available=False, name=None, vram_total_mb=None, vram_free_mb=None, source="none")

_torch: ModuleType | None = None
_torch_checked = False


def _load_torch() -> ModuleType | None:
    global _torch, _torch_checked
    if not _torch_checked:
        _torch_checked = True
        try:
            _torch = importlib.import_module("torch")
        except ImportError:
            _torch = None
    return _torch


def _from_torch() -> GpuInfo | None:
    torch = _load_torch()
    if torch is None or not torch.cuda.is_available():
        return None
    free, total = torch.cuda.mem_get_info(0)
    return GpuInfo(
        available=True,
        name=str(torch.cuda.get_device_name(0)),
        vram_total_mb=int(total) // _MB,
        vram_free_mb=int(free) // _MB,
        source="torch",
    )


def parse_nvidia_smi(output: str) -> GpuInfo | None:
    """Parse `name, memory.total, memory.free` (csv, noheader, nounits); first GPU only."""
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    parts = [part.strip() for part in lines[0].split(",")]
    if len(parts) != 3:
        return None
    try:
        total, free = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    return GpuInfo(
        available=True, name=parts[0], vram_total_mb=total, vram_free_mb=free, source="nvidia-smi"
    )


def _from_nvidia_smi() -> GpuInfo | None:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("nvidia-smi failed: %s", exc)
        return None
    return parse_nvidia_smi(result.stdout)


def gpu_info() -> GpuInfo:
    return _from_torch() or _from_nvidia_smi() or NO_GPU


@dataclass
class Usage:
    seconds: float = 0.0
    peak_vram_mb: int | None = None  # None when running on CPU


@contextmanager
def track_usage() -> Iterator[Usage]:
    """Measure wall time and peak VRAM allocated by torch inside the block."""
    torch = _load_torch()
    on_gpu = torch is not None and bool(torch.cuda.is_available())
    if torch is not None and on_gpu:
        torch.cuda.reset_peak_memory_stats()
    usage = Usage()
    start = time.perf_counter()
    try:
        yield usage
    finally:
        usage.seconds = round(time.perf_counter() - start, 2)
        if torch is not None and on_gpu:
            usage.peak_vram_mb = int(torch.cuda.max_memory_allocated()) // _MB
