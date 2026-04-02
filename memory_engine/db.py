from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from psycopg import Connection


@contextmanager
def open_connection(dsn: str) -> Iterator["Connection"]:
    from psycopg import connect

    conn = connect(dsn)
    try:
        yield conn
    finally:
        conn.close()
