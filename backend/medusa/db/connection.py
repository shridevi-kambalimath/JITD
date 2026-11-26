"""SQLite connection management.

Design notes
* One connection per unit of work (per request). SQLite connections are cheap, and this avoids
  sharing a connection across FastAPI worker threads.
* check_same_thread=False is required because FastAPI may run a yield-dependency's setup and
  teardown on different threadpool threads. The connection is still never used concurrently.
* WAL mode lets the UI read while a pipeline run writes. It is a property of the database file
  and is set once by init_db; foreign_keys and busy_timeout are per connection and set here.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

BUSY_TIMEOUT_MS = 5000


class DatabaseError(RuntimeError):
    pass


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on any exception, always close."""
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one transactional connection per request."""
    with transaction(request.app.state.settings.db_path) as conn:
        yield conn
