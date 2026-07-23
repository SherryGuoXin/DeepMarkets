from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = PROJECT_ROOT / "form13f.sqlite3"


def database_path() -> Path:
    return Path(os.environ.get("FORM13F_DATABASE", DEFAULT_DATABASE)).resolve()


def connect() -> sqlite3.Connection:
    path = database_path()
    if not path.exists():
        raise RuntimeError(f"13F database not found: {path}")
    connection = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
        timeout=30,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def rows(sql: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with connect() as connection:
        return [dict(row) for row in connection.execute(sql, tuple(parameters))]


def row(sql: str, parameters: Iterable[Any] = ()) -> dict[str, Any] | None:
    with connect() as connection:
        result = connection.execute(sql, tuple(parameters)).fetchone()
        return dict(result) if result else None


def scalar(sql: str, parameters: Iterable[Any] = ()) -> Any:
    with connect() as connection:
        result = connection.execute(sql, tuple(parameters)).fetchone()
        return result[0] if result else None
