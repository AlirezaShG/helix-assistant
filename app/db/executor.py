"""SQL safety layer 2: SQLite itself refuses anything but reading."""

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path


class SQLExecutionError(RuntimeError):
    """SQLite failed to run the query (unknown column, syntax, timeout...)."""


class SQLPermissionError(SQLExecutionError):
    """SQLite's authorizer refused the query because it tried to do more than read."""


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list] = field(default_factory=list)
    truncated: bool = False


ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),  # WITH RECURSIVE
}


def _authorizer(action: int, arg1, arg2, db_name, trigger) -> int:
    if action in ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def list_tables(db_path: Path) -> set[str]:
    """Names of the user tables (sqlite_* internal tables excluded)."""
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        return {name.lower() for (name,) in rows}


def run_read_only(db_path: Path, sql: str, max_rows: int = 200, timeout_seconds: float = 3.0) -> QueryResult:
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        conn.set_authorizer(_authorizer)

        deadline = time.monotonic() + timeout_seconds
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)

        cursor = conn.execute(sql)
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
        return QueryResult(
            columns=columns,
            rows=[list(row) for row in rows[:max_rows]],
            truncated=len(rows) > max_rows,
        )
    except sqlite3.Error as exc:
        message = str(exc)
        if "not authorized" in message or "readonly" in message:
            raise SQLPermissionError("the database refused the operation: access is read-only") from exc
        if "interrupted" in message:
            message = f"query took longer than {timeout_seconds} s and was stopped"
        raise SQLExecutionError(message) from exc
    except sqlite3.Warning as exc:
        raise SQLExecutionError(str(exc)) from exc
    finally:
        conn.close()
