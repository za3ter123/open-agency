"""Reply classification: pure keyword/heuristic bucketing of reply text.

Buckets: interested, rejected, auto_reply, other. Deterministic — no
network, no state. leadengine.replies calls classify_reply() per message
and stores the result via crm.set_reply_bucket.
"""
from __future__ import annotations

import re

BUCKET_INTERESTED = "interested"
BUCKET_REJECTED = "rejected"
BUCKET_AUTO_REPLY = "auto_reply"
BUCKET_OTHER = "other"

BUCKETS = (BUCKET_INTERESTED, BUCKET_REJECTED, BUCKET_AUTO_REPLY, BUCKET_OTHER)

# Checked in this order: auto-reply and rejection are unambiguous negative/
# neutral signals and should win over a stray "interested" keyword; a genuine
# question or "yes" only counts once those are ruled out.
_AUTO_REPLY_PATTERNS = [
    r"\bout of (the )?office\b",
    r"\bauto([\s-]?reply|[\s-]?response)\b",
    r"\bautomatic reply\b",
    r"\bon vacation\b",
    r"\bcurrently away\b",
    r"\bi(?:'m| am) away\b",
    r"\bdelivery (has )?failed\b",
    r"\bundeliverable\b",
    r"\bmailer-daemon\b",
    r"\bwill be back\b",
]

_REJECTED_PATTERNS = [
    r"\bunsubscribe\b",
    r"\bnot interested\b",
    r"\bno thanks?\b",
    r"\bno thank you\b",
    r"\bplease stop\b",
    r"\bstop (contacting|emailing|messaging) (me|us)\b",
    r"\bremove me\b",
    r"\bdo not contact\b",
    r"\bdon'?t (email|contact) (me|us) again\b",
    r"^\s*no\.?\s*$",
]

_INTERESTED_PATTERNS = [
    r"\binterested\b",
    r"\btell me more\b",
    r"\bsounds? good\b",
    r"\byes please\b",
    r"\blet'?s (talk|chat|do (it|this))\b",
    r"\bcall me\b",
    r"\bschedule a call\b",
    r"\bhow much\b",
    r"\bwhat'?s the (price|cost)\b",
    r"\bcan you\b.*\?",
    r"\?\s*$",
    r"^\s*yes\b",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE | re.MULTILINE) for p in patterns)


def classify_reply(text: str) -> str:
    """Classify one reply's plain-text body into a bucket. Pure, deterministic."""
    body = (text or "").strip()
    if not body:
        return BUCKET_OTHER
    if _matches_any(body, _AUTO_REPLY_PATTERNS):
        return BUCKET_AUTO_REPLY
    if _matches_any(body, _REJECTED_PATTERNS):
        return BUCKET_REJECTED
    if _matches_any(body, _INTERESTED_PATTERNS):
        return BUCKET_INTERESTED
    return BUCKET_OTHER
