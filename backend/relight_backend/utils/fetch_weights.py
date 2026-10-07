"""Download helper run as a separate process, so a download can be killed to cancel it.

    python -m relight_backend.utils.fetch_weights size     <repo> <revision> <cache> [patterns...]
    python -m relight_backend.utils.fetch_weights download <repo> <revision> <cache> [patterns...]

`download` prints "PROGRESS <bytes written>" lines on stdout for the parent.
Partial files stay in the cache and resume on the next run.
"""

from __future__ import annotations

import fnmatch
import os
import sys
import time
from typing import Any

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
# Plain HTTP downloads: every chunk is reported and partial files resume. The
# newer Xet transfer path reports progress in a way this script cannot follow.
os.environ["HF_HUB_DISABLE_XET"] = "1"

from huggingface_hub import HfApi, snapshot_download  # noqa: E402
from huggingface_hub.utils.tqdm import tqdm as hf_tqdm  # noqa: E402


class ReportingTqdm(hf_tqdm):
    """Silent progress bar that reports bytes written to disk on stdout.

    snapshot_download makes several bars; the one described "Reconstructing..."
    counts bytes written across all files.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._reports = str(kwargs.get("desc", "")).startswith("Reconstructing")
        self._written = 0
        self._last_print = 0.0
        kwargs["disable"] = True  # no bar drawing; a disabled bar also stops counting
        super().__init__(*args, **kwargs)

    def update(self, n: float | None = 1) -> bool | None:
        if self._reports and n:
            self._written += int(n)
            now = time.monotonic()
            if now - self._last_print > 0.3:
                self._last_print = now
                print(f"PROGRESS {self._written}", flush=True)
        return None


def total_bytes(repo_id: str, revision: str, patterns: list[str]) -> int:
    info = HfApi().model_info(repo_id, revision=revision, files_metadata=True)
    total = 0
    for sibling in info.siblings or []:
        if not patterns or any(fnmatch.fnmatch(sibling.rfilename, p) for p in patterns):
            total += sibling.size or 0
    return total


def main() -> None:
    command, repo_id, revision, cache_dir, *patterns = sys.argv[1:]
    if command == "size":
        print(total_bytes(repo_id, revision, patterns))
    elif command == "download":
        snapshot_download(
            repo_id,
            revision=revision,
            cache_dir=cache_dir,
            allow_patterns=patterns or None,
            tqdm_class=ReportingTqdm,
        )
    else:
        sys.exit(f"unknown command {command!r}")


if __name__ == "__main__":
    main()
