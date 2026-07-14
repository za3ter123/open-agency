"""SMTP outreach + follow-up scheduler on top of the CRM pipeline.

    python -m leadengine.outreach pitch <dedupe_key> --to E --subject S --body-file F
    python -m leadengine.outreach touch <dedupe_key> <touch_no> --subject S --body-file F
    python -m leadengine.outreach due

Pure stdlib: smtplib + email.message.EmailMessage + ssl for sending;
config comes from a tiny .env parser (never argv/env so SMTP_PASS never
ends up in shell history or logs).
"""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage

from .store import init_db

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "leads.db")


_DEFAULT_ENV = os.path.join(os.path.dirname(__file__), "..", ".env")


def load_env(path: str = _DEFAULT_ENV) -> dict:
    """Parse a tiny KEY=VALUE .env file into a dict.

    Blank lines and lines starting with '#' are ignored; surrounding
    single/double quotes on the value are stripped. A missing file is
    not an error -- returns {} (with defaults applied) so callers can
    fall back to CLI flags or fail loudly at send time instead.
    """
    cfg: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        lines = []

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        cfg[key] = value

    cfg.setdefault("SMTP_PORT", "587")
    cfg.setdefault("FROM_EMAIL", cfg.get("SMTP_USER", ""))
    return cfg


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no", "off")


def _from_header(cfg: dict) -> str:
    """Render the From header as 'Name <email>', or just 'email' with no name."""
    from_email = cfg.get("FROM_EMAIL") or cfg.get("SMTP_USER", "")
    from_name = cfg.get("FROM_NAME", "")
    return f"{from_name} <{from_email}>" if from_name else from_email


def send_email(cfg: dict, to: str, subject: str, body: str) -> bool:
    """Send a plain-text email per cfg. Returns False on any SMTP/network
    failure instead of raising, so a batch of follow-ups can keep going
    after one bad address. Never logs SMTP_PASS.
    """
    msg = EmailMessage()
    msg["From"] = _from_header(cfg)
    msg["To"] = to
    msg["Subject"] = subject
    reply_to = cfg.get("REPLY_TO")
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    if _is_truthy(cfg.get("DRY_RUN")):
        print("--- DRY RUN: email not sent ---")
        print(msg)
        return True

    host = cfg.get("SMTP_HOST", "")
    port = int(cfg.get("SMTP_PORT") or 587)
    user = cfg.get("SMTP_USER", "")
    password = cfg.get("SMTP_PASS", "")

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(user, password)
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        print(f"[outreach] send to {to!r} failed: {e}", file=sys.stderr)
        return False
    return True


def _fast_forward_to_deployed(conn, dedupe_key: str) -> None:
    """crm's state machine only allows touch_no=1 once a lead is 'deployed'
    (deployed -> pitched). Outreach can run standalone without the
    site-build pipeline behind it, so walk the lead through the
    intermediate stages before recording the pitch.
    """
    from . import crm

    chain = crm.STAGES[: crm.STAGES.index("deployed") + 1]
    stage = crm.get_stage(conn, dedupe_key) or "new"
    if stage not in chain:
        return  # already at/past 'deployed'
    for nxt in chain[chain.index(stage) + 1:]:
        crm.set_stage(conn, dedupe_key, nxt)


def _read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        with open(args.body_file, "r", encoding="utf-8") as f:
            return f.read()
    return args.body


def cmd_pitch(args: argparse.Namespace) -> int:
    from . import crm

    cfg = load_env()
    conn = init_db(args.db)
    crm.init_pipeline(conn)
    try:
        stage = crm.get_stage(conn, args.dedupe_key)
        if stage not in (None, "new", "enriched", "built", "qa_passed", "deployed"):
            print(
                f"[outreach] touch 1 already recorded for {args.dedupe_key!r} "
                f"(stage={stage!r})",
                file=sys.stderr,
            )
            return 2

        body = _read_body(args)
        if not send_email(cfg, args.to, args.subject, body):
            return 1

        _fast_forward_to_deployed(conn, args.dedupe_key)
        crm.set_email(conn, args.dedupe_key, args.to)
        crm.record_touch(conn, args.dedupe_key, 1, args.subject, body)
        return 0
    finally:
        conn.close()


def cmd_touch(args: argparse.Namespace) -> int:
    from . import crm

    cfg = load_env()
    conn = init_db(args.db)
    crm.init_pipeline(conn)
    try:
        row = crm.pipeline_row(conn, args.dedupe_key)
        if not row or not row.get("email"):
            print(
                f"[outreach] no email on file for {args.dedupe_key!r}; "
                "run 'pitch' first",
                file=sys.stderr,
            )
            return 2

        if not args.force:
            due = crm.due_followups(conn)
            match = next((d for d in due if d["dedupe_key"] == args.dedupe_key), None)
            if not match or match["next_touch_no"] != args.touch_no:
                expected = match["next_touch_no"] if match else "not due yet"
                print(
                    f"[outreach] touch {args.touch_no} is not due for "
                    f"{args.dedupe_key!r} (next due: {expected}); use --force to override",
                    file=sys.stderr,
                )
                return 2

        body = _read_body(args)
        if not send_email(cfg, row["email"], args.subject, body):
            return 1

        crm.record_touch(conn, args.dedupe_key, args.touch_no, args.subject, body)
        return 0
    finally:
        conn.close()


def cmd_due(args: argparse.Namespace) -> int:
    from . import crm

    conn = init_db(args.db)
    crm.init_pipeline(conn)
    try:
        rows = crm.due_followups(conn)
        if not rows:
            print("No follow-ups due.")
            return 0
        print(f"{'DEDUPE_KEY':<32} {'NAME':<24} {'TOUCH':>5} {'DUE_AT':<26} EMAIL")
        print("-" * 100)
        for r in rows:
            print(
                f"{r['dedupe_key'][:32]:<32} {(r['name'] or '')[:24]:<24} "
                f"{r['next_touch_no']:>5} {(r['due_at'] or ''):<26} {r['email'] or '-'}"
            )
        return 0
    finally:
        conn.close()


def _add_body_args(p: argparse.ArgumentParser) -> None:
    body = p.add_mutually_exclusive_group(required=True)
    body.add_argument("--body-file", help="path to UTF-8 body text file")
    body.add_argument("--body", help="body text inline")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leadengine.outreach", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    pitch = sub.add_parser("pitch", help="send the initial outreach email (touch 1)")
    pitch.add_argument("dedupe_key")
    pitch.add_argument("--to", required=True)
    pitch.add_argument("--subject", required=True)
    pitch.add_argument("--db", default=_DEFAULT_DB)
    _add_body_args(pitch)
    pitch.set_defaults(func=cmd_pitch)

    touch = sub.add_parser("touch", help="send a follow-up email (touch 2-5)")
    touch.add_argument("dedupe_key")
    touch.add_argument("touch_no", type=int, choices=[2, 3, 4, 5])
    touch.add_argument("--subject", required=True)
    touch.add_argument("--db", default=_DEFAULT_DB)
    touch.add_argument("--force", action="store_true", help="skip the due-date check")
    _add_body_args(touch)
    touch.set_defaults(func=cmd_touch)

    due = sub.add_parser("due", help="list follow-ups due now")
    due.add_argument("--db", default=_DEFAULT_DB)
    due.set_defaults(func=cmd_due)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
