"""On-disk session cache: one folder per source image, keyed by its hash.

Opening the same image again reuses the maps already computed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# aux packs the helper maps in one picture: red = where lights reach (0 = sky),
# green = square root of the photo's large-scale brightness, blue and alpha = the
# rim map (image_io.save_aux).
# v2 added the rim map, v3 rounds it by how thick the shape is, v4 leaves out strays and
# uncertain parts of the mask; a session with only an older file gets a new one.
AUX_FILE = "aux_v4.png"
MAP_NAMES = ("albedo_proxy", "normal", "normal_smooth", "depth", "mask", "aux")
ORIGINAL_FILE = "original.bin"
META_FILE = "meta.json"

_SESSION_ID = re.compile(r"^[0-9a-f]{20}$")


@dataclass
class SessionMeta:
    id: str
    source_name: str
    original_size: tuple[int, int]  # (width, height)
    working_size: tuple[int, int]
    normals_method: str
    mask_model: str
    stats: dict[str, Any] = field(default_factory=dict)


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, image_bytes: bytes) -> str:
        """Store the original bytes; return the session id (hash of the image)."""
        session_id = hashlib.sha256(image_bytes).hexdigest()[:20]
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True)
        original = folder / ORIGINAL_FILE
        if not original.exists():
            original.write_bytes(image_bytes)
        return session_id

    def folder(self, session_id: str) -> Path | None:
        """Folder of an existing session, or None. Rejects ids that are not ours."""
        if not _SESSION_ID.match(session_id):
            return None
        folder = self.root / session_id
        return folder if folder.is_dir() else None

    def load_meta(self, session_id: str) -> SessionMeta | None:
        folder = self.folder(session_id)
        if folder is None or not (folder / META_FILE).exists():
            return None
        data = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
        data["original_size"] = tuple(data["original_size"])
        data["working_size"] = tuple(data["working_size"])
        return SessionMeta(**data)

    def save_meta(self, meta: SessionMeta) -> None:
        path = self.root / meta.id / META_FILE
        path.write_text(json.dumps(asdict(meta), indent=2), encoding="utf-8")

    def map_path(self, session_id: str, name: str) -> Path | None:
        """File for a map of a finished session, or None if it does not exist."""
        folder = self.folder(session_id)
        meta = self.load_meta(session_id)
        if folder is None or meta is None or name not in MAP_NAMES:
            return None
        path = folder / map_file(name, meta.normals_method)
        return path if path.exists() else None


def map_file(name: str, normals_method: str) -> str:
    """Normals are stored per method so switching method keeps the others cached."""
    if name in ("normal", "normal_smooth"):
        return f"{name}_{normals_method}.png"
    if name == "aux":
        return AUX_FILE
    return f"{name}.png"
