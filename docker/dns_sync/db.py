"""SQLite sync history"""

import os
import sqlite3
from typing import Optional


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_db(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = _connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS sync_runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            server_name  TEXT NOT NULL,
            server_type  TEXT NOT NULL,
            role         TEXT NOT NULL,
            started_at   TEXT NOT NULL,
            finished_at  TEXT,
            added        INTEGER DEFAULT 0,
            removed      INTEGER DEFAULT 0,
            conflicts    INTEGER DEFAULT 0,
            error        TEXT,
            status       TEXT NOT NULL DEFAULT 'success',
            a_records    INTEGER DEFAULT 0,
            cname_records INTEGER DEFAULT 0
        )
    """)
    # Migrate existing DB: add per-type record count columns if missing
    cols = {r[1] for r in con.execute("PRAGMA table_info(sync_runs)").fetchall()}
    if "a_records" not in cols:
        con.execute("ALTER TABLE sync_runs ADD COLUMN a_records INTEGER DEFAULT 0")
    if "cname_records" not in cols:
        con.execute("ALTER TABLE sync_runs ADD COLUMN cname_records INTEGER DEFAULT 0")
    con.execute("""
        CREATE TABLE IF NOT EXISTS authoritative_records (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            hub_name    TEXT NOT NULL,
            record_type TEXT NOT NULL,
            record_str  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS cache_meta (
            hub_name     TEXT PRIMARY KEY,
            last_updated TEXT NOT NULL
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS spoke_records (
            spoke_name   TEXT NOT NULL,
            record_type  TEXT NOT NULL,
            record_str   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (spoke_name, record_type, record_str)
        )
    """)
    # Migrate legacy hub_records data if present
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "hub_records" in tables:
        existing = con.execute(
            "SELECT COUNT(*) FROM authoritative_records"
        ).fetchone()[0]
        if existing == 0:
            con.execute("""
                INSERT INTO authoritative_records (hub_name, record_type, record_str, updated_at)
                SELECT hub_name, record_type, record_str, updated_at FROM hub_records
            """)
    con.commit()
    con.close()


def save_hub_records(db_path: str, hub_name: str, records: dict):
    """Replace cached records for this hub atomically."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con = _connect(db_path)
    con.execute(
        "DELETE FROM authoritative_records WHERE hub_name = ?", (hub_name,)
    )
    for record_type, record_set in records.items():
        for record_str in record_set:
            con.execute(
                "INSERT INTO authoritative_records "
                "(hub_name, record_type, record_str, updated_at) VALUES (?, ?, ?, ?)",
                (hub_name, record_type, record_str, now),
            )
    con.execute(
        "INSERT OR REPLACE INTO cache_meta (hub_name, last_updated) VALUES (?, ?)",
        (hub_name, now),
    )
    con.commit()
    con.close()


def get_cached_hub_records(db_path: str, hub_name: str) -> Optional[dict]:
    """Load cached hub records. Returns None if no cache exists yet."""
    con = _connect(db_path)
    rows = con.execute(
        "SELECT record_type, record_str FROM authoritative_records WHERE hub_name = ?",
        (hub_name,),
    ).fetchall()
    con.close()
    if not rows:
        return None
    records: dict = {}
    for record_type, record_str in rows:
        records.setdefault(record_type, set()).add(record_str)
    return records


def get_cache_last_updated(db_path: str, hub_name: str) -> Optional[str]:
    """Return ISO timestamp of last hub cache refresh, or None."""
    con = _connect(db_path)
    row = con.execute(
        "SELECT last_updated FROM cache_meta WHERE hub_name = ?", (hub_name,)
    ).fetchone()
    con.close()
    return row[0] if row else None


def get_cache_record_counts(db_path: str, hub_name: str) -> dict:
    """Return {record_type: count} for cached hub records. e.g. {'A': 12, 'CNAME': 5}"""
    con = _connect(db_path)
    rows = con.execute(
        "SELECT record_type, COUNT(*) FROM authoritative_records WHERE hub_name = ? GROUP BY record_type",
        (hub_name,),
    ).fetchall()
    con.close()
    return {row[0]: row[1] for row in rows}


def save_spoke_records(db_path: str, spoke_name: str, records: dict):
    """Replace stored records for this spoke atomically (DELETE + INSERT)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con = _connect(db_path)
    con.execute("DELETE FROM spoke_records WHERE spoke_name = ?", (spoke_name,))
    for record_type, record_set in records.items():
        for record_str in record_set:
            con.execute(
                "INSERT INTO spoke_records (spoke_name, record_type, record_str, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (spoke_name, record_type, record_str, now),
            )
    con.commit()
    con.close()


def get_spoke_records(db_path: str, spoke_name: str) -> Optional[dict]:
    """Load stored spoke records. Returns None if no state stored yet."""
    con = _connect(db_path)
    rows = con.execute(
        "SELECT record_type, record_str FROM spoke_records WHERE spoke_name = ?",
        (spoke_name,),
    ).fetchall()
    con.close()
    if not rows:
        return None
    records: dict = {}
    for record_type, record_str in rows:
        records.setdefault(record_type, set()).add(record_str)
    return records


def get_spoke_record_counts(db_path: str, spoke_name: str) -> dict:
    """Return {record_type: count} for stored spoke records. e.g. {'A': 12, 'CNAME': 5}"""
    con = _connect(db_path)
    rows = con.execute(
        "SELECT record_type, COUNT(*) FROM spoke_records WHERE spoke_name = ? GROUP BY record_type",
        (spoke_name,),
    ).fetchall()
    con.close()
    return {row[0]: row[1] for row in rows}


def record_sync(
    db_path: str,
    server_name: str,
    server_type: str,
    role: str,
    stats: dict,
    error: Optional[str] = None,
):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    status = "error" if error else "success"
    con = _connect(db_path)
    con.execute(
        """
        INSERT INTO sync_runs
            (server_name, server_type, role, started_at, finished_at,
             added, removed, conflicts, error, status, a_records, cname_records)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_name, server_type, role, now, now,
            stats.get("added", 0), stats.get("removed", 0),
            stats.get("conflicts", 0), error, status,
            stats.get("a_records", 0), stats.get("cname_records", 0),
        ),
    )
    con.commit()
    con.close()


def get_history(db_path: str, limit: int = 50, server_name: str = None) -> list:
    con = _connect(db_path)
    con.row_factory = sqlite3.Row
    if server_name:
        rows = con.execute(
            "SELECT * FROM sync_runs WHERE server_name = ? ORDER BY started_at DESC LIMIT ?",
            (server_name, limit),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def clear_history(db_path: str, server_name: str = None):
    """Delete sync_runs rows, optionally filtered to one server."""
    con = _connect(db_path)
    if server_name:
        con.execute("DELETE FROM sync_runs WHERE server_name = ?", (server_name,))
    else:
        con.execute("DELETE FROM sync_runs")
    con.commit()
    con.close()


def get_last_sync(db_path: str, server_name: str) -> Optional[dict]:
    con = _connect(db_path)
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM sync_runs WHERE server_name = ? ORDER BY started_at DESC LIMIT 1",
        (server_name,),
    ).fetchone()
    con.close()
    return dict(row) if row else None
