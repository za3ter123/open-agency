"""Tiny SQLite CRM for leads. Dedupes on Lead.dedupe_key()."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .models import Lead

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    dedupe_key TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT,
    address    TEXT,
    phone      TEXT,
    rating     REAL,
    reviews    INTEGER,
    has_website INTEGER NOT NULL,
    maps_url   TEXT,
    source     TEXT,
    score      INTEGER NOT NULL,
    reasons    TEXT,
    status     TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);
"""


def init_db(path: str) -> sqlite3.Connection:
    """Open (or create) the CRM db and ensure schema. Idempotent."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def upsert_lead(
    conn: sqlite3.Connection, lead: Lead, score: int, reasons: list[str]
) -> None:
    """Insert or update a lead, deduped on dedupe_key.

    Re-scraping the same lead refreshes the scraped fields + score but:
      - never creates a duplicate row,
      - preserves the original created_at,
      - preserves a non-'new' status (don't clobber 'contacted'/'won'/etc.).
    """
    key = lead.dedupe_key()
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute(
        "SELECT created_at, status FROM leads WHERE dedupe_key = ?", (key,)
    ).fetchone()
    created_at = row["created_at"] if row else now
    status = row["status"] if row else "new"  # keep prior status on re-scrape

    conn.execute(
        """
        INSERT INTO leads (dedupe_key, name, category, address, phone, rating,
                           reviews, has_website, maps_url, source, score,
                           reasons, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(dedupe_key) DO UPDATE SET
            name=excluded.name, category=excluded.category,
            address=excluded.address, phone=excluded.phone,
            rating=excluded.rating, reviews=excluded.reviews,
            has_website=excluded.has_website, maps_url=excluded.maps_url,
            source=excluded.source, score=excluded.score,
            reasons=excluded.reasons
        """,
        (
            key, lead.name, lead.category, lead.address, lead.phone,
            lead.rating, lead.reviews, int(lead.has_website), lead.maps_url,
            lead.source, score, json.dumps(reasons), status, created_at,
        ),
    )
    conn.commit()


def all_leads(conn: sqlite3.Connection, order_by_score: bool = True) -> list[dict]:
    """Return all leads as dicts. Highest score first by default."""
    order = "ORDER BY score DESC, reviews DESC" if order_by_score else "ORDER BY name"
    rows = conn.execute(f"SELECT * FROM leads {order}").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["has_website"] = bool(d["has_website"])
        d["reasons"] = json.loads(d["reasons"]) if d["reasons"] else []
        out.append(d)
    return out


def set_status(conn: sqlite3.Connection, dedupe_key: str, status: str) -> None:
    """Update CRM status for a lead (e.g. 'contacted', 'won', 'lost')."""
    conn.execute(
        "UPDATE leads SET status = ? WHERE dedupe_key = ?", (status, dedupe_key)
    )
    conn.commit()
