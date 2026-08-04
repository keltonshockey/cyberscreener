"""
Read-only SQLite access — the single door every research/analysis path uses.

Rebuild plan section 0 makes data preservation the prime directive: nothing the
collector has gathered may be modified or deleted by anything downstream of it.
The enforcement here is mechanical rather than conventional — a connection opened
through `file:...?mode=ro` cannot write, so an accidental INSERT/UPDATE/DELETE in
a research script fails loudly at the sqlite layer instead of quietly mutating
the production store.

Later sessions (R2 IC harness, R3 PIT program, R4 cohort logger) import this
instead of rolling their own `sqlite3.connect`. See research/README.md rule 1.
"""

import os
import sqlite3
from urllib.parse import quote


def ro_uri(path: str) -> str:
    """Build the `file:...?mode=ro` URI for `path` (absolute, percent-encoded)."""
    abs_path = os.path.abspath(os.path.expanduser(path))
    # sqlite URI filenames are URL-syntax: '?' and '#' would start the query or
    # fragment, and spaces are illegal. quote() with '/' kept safe handles all of it.
    return f"file:{quote(abs_path, safe='/')}?mode=ro"


def connect_ro(path: str) -> sqlite3.Connection:
    """
    Open `path` strictly read-only and return the connection.

    Raises sqlite3.OperationalError if the database does not exist — `mode=ro`
    never creates a file, which is deliberate: a typo'd path fails instead of
    silently producing an empty DB and an empty analysis.

    Any write attempted through the returned connection raises
    sqlite3.OperationalError("attempt to write a readonly database").
    """
    conn = sqlite3.connect(ro_uri(path), uri=True)
    conn.row_factory = sqlite3.Row
    # Match the reader-side pragmas used by db.models.get_db, minus anything that
    # would need a write lock. query_only is belt-and-braces on top of mode=ro.
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA cache_size=-32768")
    conn.execute("PRAGMA mmap_size=0")
    return conn
