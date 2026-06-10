"""SQLite snapshot storage for Polymarket monitoring.

Tables:
  snapshots  - odds snapshots per (event_id, outcome_name), retained 7 days
  alert_log  - history of alerts sent, used for cooldown logic
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "snapshots.db"

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT    NOT NULL,
    event_title TEXT,
    question    TEXT,
    outcome     TEXT    NOT NULL,
    price       REAL    NOT NULL,
    volume24hr  REAL,
    liquidity   REAL,
    event_url   TEXT,
    end_date    TEXT,
    snapped_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snap
    ON snapshots(event_id, outcome, snapped_at DESC);

CREATE TABLE IF NOT EXISTS alert_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT    NOT NULL,
    event_title TEXT,
    outcome     TEXT    NOT NULL,
    old_price   REAL,
    new_price   REAL,
    price_delta REAL,
    alert_type  TEXT,
    alerted_at  TEXT    DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_alert
    ON alert_log(event_id, outcome, alerted_at DESC);

CREATE TABLE IF NOT EXISTS seen_trades (
    trade_id   TEXT PRIMARY KEY,
    event_id   TEXT,
    seen_at    TEXT DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def get_last_snapshot(event_id: str, outcome: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            """SELECT price, volume24hr, snapped_at
               FROM snapshots
               WHERE event_id = ? AND outcome = ?
               ORDER BY snapped_at DESC LIMIT 1""",
            (event_id, outcome),
        ).fetchone()
    return dict(row) if row else None


def save_snapshot(market: dict, outcome: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO snapshots
               (event_id, event_title, question, outcome,
                price, volume24hr, liquidity, event_url, end_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                market["event_id"],
                market["title"],
                market["question"],
                outcome["name"],
                outcome["price"],
                market.get("volume24hr"),
                market.get("liquidity"),
                market.get("url"),
                market.get("end_date"),
            ),
        )


def log_alert(market: dict, outcome: dict, old_price: float, alert_type: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO alert_log
               (event_id, event_title, outcome, old_price, new_price, price_delta, alert_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                market["event_id"],
                market["title"],
                outcome["name"],
                old_price,
                outcome["price"],
                outcome["price"] - old_price,
                alert_type,
            ),
        )


def was_recently_alerted(event_id: str, outcome: str, cooldown_hours: int = 2) -> bool:
    """Return True if this outcome was already alerted within the cooldown window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with _connect() as conn:
        row = conn.execute(
            """SELECT 1 FROM alert_log
               WHERE event_id = ? AND outcome = ? AND alerted_at > ?
               LIMIT 1""",
            (event_id, outcome, cutoff),
        ).fetchone()
    return row is not None


def cleanup_old_snapshots(keep_days: int = 7) -> int:
    """Delete snapshots older than keep_days. Returns number of rows deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with _connect() as conn:
        cur = conn.execute("DELETE FROM snapshots WHERE snapped_at < ?", (cutoff,))
        return cur.rowcount


def is_trade_seen(trade_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_trades WHERE trade_id = ? LIMIT 1", (trade_id,)
        ).fetchone()
    return row is not None


def mark_trade_seen(trade_id: str, event_id: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_trades (trade_id, event_id) VALUES (?, ?)",
            (trade_id, event_id),
        )


def cleanup_old_seen_trades(keep_hours: int = 24) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=keep_hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    with _connect() as conn:
        cur = conn.execute("DELETE FROM seen_trades WHERE seen_at < ?", (cutoff,))
        return cur.rowcount
