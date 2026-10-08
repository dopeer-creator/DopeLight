"""Locations for app data that lives outside the install folder."""

from __future__ import annotations

import os
from pathlib import Path

from relight_backend.constants import APP_NAME, DATA_DIR_ENV, LEGACY_APP_NAMES


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_data_dir() -> Path:
    """Return the data root: $RELIGHT_DATA_DIR if set, else %APPDATA%/<APP_NAME>."""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return _ensure(Path(override))
    base = Path(os.environ.get("APPDATA") or str(Path.home() / ".local" / "share"))
    current = base / APP_NAME
    if not current.exists():
        # Renamed app: keep the gigabytes of models downloaded under the old name.
        for legacy in LEGACY_APP_NAMES:
            if (base / legacy).is_dir():
                try:
                    (base / legacy).rename(current)
                except OSError:
                    pass  # in use or not permitted: start fresh, leave the old folder
                break
    return _ensure(current)


def logs_dir() -> Path:
    return _ensure(app_data_dir() / "logs")


def models_dir() -> Path:
    return _ensure(app_data_dir() / "models")


def sessions_dir() -> Path:
    return _ensure(app_data_dir() / "sessions")
