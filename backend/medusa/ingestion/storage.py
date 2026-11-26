"""Storage of original uploaded files.

* Files are stored as <document_id>.<format>. The user's filename is never part of a path,
  so path traversal ('../../x'), Windows device names ('CON') and odd characters cannot matter.
* Writes go to a temporary file first and are moved into place atomically (os.replace), so a
  crash never leaves a half-written file under a real name.
* Every resolved path is checked to be inside the upload directory.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

_NAME = re.compile(r"^DOC-[0-9A-F]{16}\.(pdf|txt)$")


class FileStore:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, name: str) -> Path:
        if not _NAME.match(name):
            raise ValueError(f"invalid storage name {name!r}")
        path = (self.root / name).resolve()
        if path.parent != self.root.resolve():
            raise ValueError("storage path escapes the upload directory")
        return path

    def save(self, document_id: str, file_format: str, data: bytes) -> str:
        name = f"{document_id}.{file_format}"
        path = self._path(name)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return name

    def read(self, name: str) -> bytes:
        return self._path(name).read_bytes()

    def delete(self, name: str) -> bool:
        if not name:  # rows migrated from schema v1 have no stored file
            return False
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False
