"""IMAP reply detection: scan the inbox and auto-mark leads 'replied'.

    python -m leadengine.replies            # scan last 30 days
    python -m leadengine.replies --days 7
    python -m leadengine.replies --sort      # classify replies into buckets

Reuses the SMTP credentials from .env (IMAP_HOST/IMAP_USER/IMAP_PASS
override if the inbox lives elsewhere). A lead in 'pitched'/'follow_up'
whose email appears as a sender in the inbox moves to 'replied', which
stops the follow-up sequence. Pure stdlib: imaplib + email.utils.
"""
from __future__ import annotations

import argparse
import email
import imaplib
import os
import sys
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import parseaddr

from .outreach import load_env
from .replysort import classify_reply
from .store import init_db

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "leads.db")


def imap_host(cfg: dict) -> str:
    """IMAP_HOST if set, else derive from SMTP_HOST (smtp.x.com -> imap.x.com)."""
    explicit = cfg.get("IMAP_HOST", "")
    if explicit:
        return explicit
    smtp = cfg.get("SMTP_HOST", "")
    if smtp.startswith("smtp."):
        return "imap." + smtp[len("smtp."):]
    return smtp


def extract_sender(from_header: str) -> str:
    """Lowercased address from a From header value; '' if unparseable."""
    addr = parseaddr(from_header)[1].strip().lower()
    return addr if "@" in addr else ""


def candidates(conn) -> dict[str, str]:
    """email -> dedupe_key for leads awaiting a reply (pitched/follow_up)."""
    rows = conn.execute(
        "SELECT dedupe_key, email FROM pipeline "
        "WHERE stage IN ('pitched', 'follow_up') AND email IS NOT NULL"
    ).fetchall()
    return {r["email"].strip().lower(): r["dedupe_key"] for r in rows if r["email"]}


def apply_replies(conn, senders) -> list[str]:
    """Mark every candidate lead whose email is in `senders` as 'replied'.
    Returns the dedupe_keys marked. Idempotent: already-replied leads are
    no longer candidates, so a re-run is a no-op."""
    from . import crm

    lookup = candidates(conn)
    marked: list[str] = []
    for sender in senders:
        key = lookup.pop((sender or "").strip().lower(), None)
        if key is None:
            continue
        crm.set_stage(conn, key, "replied")
        marked.append(key)
    return marked


def fetch_senders(cfg: dict, days: int = 30) -> list[str]:
    """Sender addresses of all inbox messages from the last `days` days.
    Read-only (BODY.PEEK); never flags messages as seen."""
    host = imap_host(cfg)
    user = cfg.get("IMAP_USER") or cfg.get("SMTP_USER", "")
    password = cfg.get("IMAP_PASS") or cfg.get("SMTP_PASS", "")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")

    senders: list[str] = []
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, f"(SINCE {since})")
        if status != "OK":
            return senders
        for num in data[0].split():
            status, msg = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
            if status != "OK" or not msg or not msg[0]:
                continue
            header = msg[0][1].decode("utf-8", errors="replace")
            sender = extract_sender(header.partition(":")[2])
            if sender:
                senders.append(sender)
    return senders


def _plain_text_body(msg: Message) -> str:
    """Best-effort plain-text body extraction. Falls back to '' rather
    than raising on odd/multipart-only messages."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                except (LookupError, ValueError):
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True)
    except (LookupError, ValueError):
        return ""
    if payload is None:
        return ""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def sort_candidates(conn) -> dict[str, str]:
    """email -> dedupe_key for leads that have ever been pitched, so a
    reply can be classified regardless of whether it already flipped the
    lead to 'replied'."""
    rows = conn.execute(
        "SELECT dedupe_key, email FROM pipeline "
        "WHERE stage IN ('pitched', 'follow_up', 'replied') AND email IS NOT NULL"
    ).fetchall()
    return {r["email"].strip().lower(): r["dedupe_key"] for r in rows if r["email"]}


def fetch_messages(cfg: dict, days: int = 30) -> list[dict]:
    """Full sender + plain-text body for every inbox message in the last
    `days` days. Read-only (BODY.PEEK); never flags messages as seen."""
    host = imap_host(cfg)
    user = cfg.get("IMAP_USER") or cfg.get("SMTP_USER", "")
    password = cfg.get("IMAP_PASS") or cfg.get("SMTP_PASS", "")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")

    messages: list[dict] = []
    with imaplib.IMAP4_SSL(host) as imap:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, f"(SINCE {since})")
        if status != "OK":
            return messages
        for num in data[0].split():
            status, msg_data = imap.fetch(num, "(BODY.PEEK[])")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            parsed = email.message_from_bytes(raw)
            sender = extract_sender(parsed.get("From", ""))
            if not sender:
                continue
            messages.append({
                "sender": sender,
                "subject": parsed.get("Subject", ""),
                "body": _plain_text_body(parsed),
            })
    return messages


def sort_replies(conn, messages: list[dict]) -> dict[str, list[dict]]:
    """Classify each message from a known lead into a bucket, storing the
    classification on the lead's pipeline row. Returns messages grouped
    by bucket (each entry also carries dedupe_key + bucket)."""
    from . import crm

    lookup = sort_candidates(conn)
    grouped: dict[str, list[dict]] = {b: [] for b in ("interested", "rejected", "auto_reply", "other")}
    for msg in messages:
        key = lookup.get(msg["sender"])
        if key is None:
            continue
        bucket = classify_reply(msg["body"])
        crm.set_reply_bucket(conn, key, bucket)
        grouped[bucket].append({**msg, "dedupe_key": key})
    return grouped


def _print_sorted(grouped: dict[str, list[dict]]) -> None:
    order = ["interested", "rejected", "auto_reply", "other"]
    labels = {
        "interested": "*** INTERESTED ***",
        "rejected": "REJECTED",
        "auto_reply": "AUTO-REPLY",
        "other": "OTHER",
    }
    total = sum(len(v) for v in grouped.values())
    if total == 0:
        print("No classified replies.")
        return
    for bucket in order:
        rows = grouped[bucket]
        if not rows:
            continue
        print(f"\n{labels[bucket]} ({len(rows)})")
        print("-" * 60)
        for r in rows:
            print(f"  {r['dedupe_key']:<32} {r['sender']:<28} {r['subject']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leadengine.replies", description=__doc__)
    p.add_argument("--days", type=int, default=30, help="inbox lookback window")
    p.add_argument("--sort", action="store_true",
                    help="classify replies into interested/rejected/auto_reply/other")
    p.add_argument("--db", default=_DEFAULT_DB)
    args = p.parse_args(argv)

    cfg = load_env()
    if not imap_host(cfg):
        print("[replies] no IMAP_HOST/SMTP_HOST in .env; run the wizard first", file=sys.stderr)
        return 2

    conn = init_db(args.db)
    from . import crm

    crm.init_pipeline(conn)
    try:
        if args.sort:
            if not sort_candidates(conn):
                print("No leads to sort replies for.")
                return 0
            try:
                messages = fetch_messages(cfg, days=args.days)
            except (imaplib.IMAP4.error, OSError) as e:
                print(f"[replies] IMAP fetch failed: {e}", file=sys.stderr)
                return 1
            grouped = sort_replies(conn, messages)
            _print_sorted(grouped)
            return 0

        if not candidates(conn):
            print("No leads awaiting a reply.")
            return 0
        try:
            senders = fetch_senders(cfg, days=args.days)
        except (imaplib.IMAP4.error, OSError) as e:
            print(f"[replies] IMAP fetch failed: {e}", file=sys.stderr)
            return 1
        marked = apply_replies(conn, senders)
        if marked:
            for key in marked:
                print(f"replied: {key}")
        else:
            print("No new replies.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
