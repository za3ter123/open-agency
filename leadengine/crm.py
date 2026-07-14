"""Pipeline CRM layer on top of the leads table in store.py.

Tracks a lead through the outreach pipeline (enrichment -> site build -> QA
-> deploy -> pitch -> follow-ups -> reply/win/dead) and the individual
outreach touches (emails) sent along the way. Lives in the same SQLite db
as leads; leadengine.store owns the `leads` table, this module owns
`pipeline` and `touches`.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline (
    dedupe_key TEXT PRIMARY KEY,
    stage TEXT NOT NULL DEFAULT 'new',
    enriched_json TEXT,
    site_dir TEXT,
    site_url TEXT,
    qa_report TEXT,
    email TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS touches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL,
    touch_no INTEGER NOT NULL,
    channel TEXT NOT NULL DEFAULT 'email',
    subject TEXT,
    body TEXT,
    sent_at TEXT NOT NULL,
    UNIQUE(dedupe_key, touch_no)
);
"""

STAGES = [
    "new", "enriched", "built", "qa_passed", "deployed",
    "pitched", "follow_up", "replied", "won", "dead",
]

# Allowed forward transitions. Any stage may also move to 'dead' (handled
# separately in set_stage rather than repeated in every set below).
TRANSITIONS: dict[str, set[str]] = {
    "new": {"enriched"},
    "enriched": {"built"},
    "built": {"qa_passed"},
    "qa_passed": {"deployed"},
    "deployed": {"pitched"},
    "pitched": {"follow_up", "replied", "dead"},
    "follow_up": {"follow_up", "replied", "dead"},
    "replied": {"won", "dead"},
    "won": set(),
    "dead": set(),
}

# Touch 1 is the pitch (day 0). Touches 2-5 are follow-ups; offset[i] is the
# number of days after the touch-1 send date that touch (i+2) is due.
FOLLOWUP_OFFSETS_DAYS = [2, 5, 9, 14]


def init_pipeline(conn: sqlite3.Connection) -> None:
    """Create the pipeline + touches tables if missing. Idempotent."""
    conn.executescript(_SCHEMA)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def ensure_row(conn: sqlite3.Connection, dedupe_key: str) -> None:
    """Insert a fresh 'new' pipeline row for dedupe_key if it doesn't exist yet.

    Every other function in this module calls this first so callers never
    have to remember to seed the row themselves.
    """
    conn.execute(
        "INSERT OR IGNORE INTO pipeline (dedupe_key, stage, updated_at) "
        "VALUES (?, 'new', ?)",
        (dedupe_key, _now()),
    )
    conn.commit()


def get_stage(conn: sqlite3.Connection, dedupe_key: str) -> str | None:
    """Current stage, or None if the lead has no pipeline row yet."""
    row = conn.execute(
        "SELECT stage FROM pipeline WHERE dedupe_key = ?", (dedupe_key,)
    ).fetchone()
    return row["stage"] if row else None


def set_stage(
    conn: sqlite3.Connection, dedupe_key: str, stage: str, now: str | None = None
) -> None:
    """Move a lead to `stage`, enforcing the pipeline state machine.

    Raises ValueError for an unknown stage or a transition that isn't in
    TRANSITIONS (any stage -> 'dead' is always allowed, since a lead can
    go cold at any point in the pipeline).
    """
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage!r}")
    ensure_row(conn, dedupe_key)
    current = get_stage(conn, dedupe_key)
    if stage != "dead" and stage not in TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid transition: {current!r} -> {stage!r}")
    conn.execute(
        "UPDATE pipeline SET stage = ?, updated_at = ? WHERE dedupe_key = ?",
        (stage, now or _now(), dedupe_key),
    )
    conn.commit()


def save_enrichment(
    conn: sqlite3.Connection, dedupe_key: str, data: dict, now: str | None = None
) -> None:
    """Store enrichment payload; bump 'new' -> 'enriched' automatically."""
    ensure_row(conn, dedupe_key)
    ts = now or _now()
    conn.execute(
        "UPDATE pipeline SET enriched_json = ?, updated_at = ? WHERE dedupe_key = ?",
        (json.dumps(data), ts, dedupe_key),
    )
    conn.commit()
    if get_stage(conn, dedupe_key) == "new":
        set_stage(conn, dedupe_key, "enriched", now=ts)


def set_site(
    conn: sqlite3.Connection,
    dedupe_key: str,
    site_dir: str,
    site_url: str | None = None,
    now: str | None = None,
) -> None:
    """Record where the generated site lives. Caller drives the 'built'
    stage transition explicitly via set_stage once the build succeeds."""
    ensure_row(conn, dedupe_key)
    conn.execute(
        "UPDATE pipeline SET site_dir = ?, site_url = ?, updated_at = ? "
        "WHERE dedupe_key = ?",
        (site_dir, site_url, now or _now(), dedupe_key),
    )
    conn.commit()


def set_qa(
    conn: sqlite3.Connection,
    dedupe_key: str,
    report: dict,
    passed: bool,
    now: str | None = None,
) -> None:
    """Store the QA report. Only a pass advances the stage to 'qa_passed';
    a fail leaves the lead in 'built' so it can be rebuilt and re-QA'd."""
    ensure_row(conn, dedupe_key)
    ts = now or _now()
    conn.execute(
        "UPDATE pipeline SET qa_report = ?, updated_at = ? WHERE dedupe_key = ?",
        (json.dumps(report), ts, dedupe_key),
    )
    conn.commit()
    if passed:
        set_stage(conn, dedupe_key, "qa_passed", now=ts)


def set_email(conn: sqlite3.Connection, dedupe_key: str, email: str) -> None:
    """Record the outreach email address for a lead (leads.py has no email
    column; scraped leads only carry a phone number)."""
    ensure_row(conn, dedupe_key)
    conn.execute(
        "UPDATE pipeline SET email = ?, updated_at = ? WHERE dedupe_key = ?",
        (email, _now(), dedupe_key),
    )
    conn.commit()


def record_touch(
    conn: sqlite3.Connection,
    dedupe_key: str,
    touch_no: int,
    subject: str | None,
    body: str | None,
    channel: str = "email",
    sent_at: str | None = None,
) -> None:
    """Log one outreach touch. touch_no=1 is the initial pitch (-> stage
    'pitched'); touch_no 2-5 are follow-ups (-> stage 'follow_up').

    Uses INSERT OR IGNORE on the (dedupe_key, touch_no) unique constraint:
    a retried/duplicate send for a touch_no already on file is silently
    dropped rather than raising, so a crashed-and-retried send job stays
    idempotent instead of crashing the caller. If the insert is ignored we
    also skip the stage transition, since nothing new actually happened.
    """
    ensure_row(conn, dedupe_key)
    sent = sent_at or _now()
    cur = conn.execute(
        "INSERT OR IGNORE INTO touches "
        "(dedupe_key, touch_no, channel, subject, body, sent_at) "
        "VALUES (?,?,?,?,?,?)",
        (dedupe_key, touch_no, channel, subject, body, sent),
    )
    conn.commit()
    if cur.rowcount == 0:
        return
    if touch_no == 1:
        set_stage(conn, dedupe_key, "pitched", now=sent)
    elif 2 <= touch_no <= 5:
        set_stage(conn, dedupe_key, "follow_up", now=sent)


def due_followups(conn: sqlite3.Connection, now: str | None = None) -> list[dict]:
    """Leads sitting in 'pitched'/'follow_up' whose next follow-up is due.

    due date = touch-1 sent_at + FOLLOWUP_OFFSETS_DAYS[next_touch_no - 2].
    Skips leads with no touch 1 yet, and caps at touch 5 (5 touches total:
    1 pitch + 4 follow-ups).
    """
    now_dt = _parse(now) if now else datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT p.dedupe_key, p.email, l.name
        FROM pipeline p
        LEFT JOIN leads l ON l.dedupe_key = p.dedupe_key
        WHERE p.stage IN ('pitched', 'follow_up')
        """
    ).fetchall()

    due: list[dict] = []
    for row in rows:
        touches = conn.execute(
            "SELECT touch_no, sent_at FROM touches WHERE dedupe_key = ? "
            "ORDER BY touch_no",
            (row["dedupe_key"],),
        ).fetchall()
        touch_nos = [t["touch_no"] for t in touches]
        if 1 not in touch_nos or len(touches) >= 5:
            continue
        touch1_sent_at = next(t["sent_at"] for t in touches if t["touch_no"] == 1)
        next_touch_no = max(touch_nos) + 1
        if next_touch_no > 5:
            continue
        offset_days = FOLLOWUP_OFFSETS_DAYS[next_touch_no - 2]
        due_at = _parse(touch1_sent_at) + timedelta(days=offset_days)
        if due_at <= now_dt:
            due.append({
                "dedupe_key": row["dedupe_key"],
                "next_touch_no": next_touch_no,
                "due_at": due_at.isoformat(),
                "email": row["email"],
                "name": row["name"],
            })
    return due


def pipeline_row(conn: sqlite3.Connection, dedupe_key: str) -> dict | None:
    """Full pipeline row for a lead, with JSON columns decoded."""
    row = conn.execute(
        "SELECT * FROM pipeline WHERE dedupe_key = ?", (dedupe_key,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["enriched_json"] = json.loads(d["enriched_json"]) if d["enriched_json"] else None
    d["qa_report"] = json.loads(d["qa_report"]) if d["qa_report"] else None
    return d


def board(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """All pipeline rows grouped by stage, joined with leads.name/phone —
    the data behind a kanban-style status display."""
    rows = conn.execute(
        """
        SELECT p.*, l.name, l.phone
        FROM pipeline p
        LEFT JOIN leads l ON l.dedupe_key = p.dedupe_key
        """
    ).fetchall()
    out: dict[str, list[dict]] = {stage: [] for stage in STAGES}
    for row in rows:
        d = dict(row)
        out.setdefault(d["stage"], []).append(d)
    return out
