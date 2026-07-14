"""Pure buy-likelihood scoring for a Lead.

Deterministic, side-effect free. This is the unit-tested core of the engine.
The thesis: a local business with NO website but clear signs of being a real,
established, reachable operation is the highest-value cold lead for a website
agency. We score those signals 0-100.
"""
from __future__ import annotations

from .models import Lead

# Tunable weights. Each maps to one human-readable buy-signal.
BASE = 30          # baseline: it's a no-website business, already a target
PHONE_PTS = 20     # reachable -> we can actually pitch them
HAS_REVIEWS = 15   # has any reviews -> real, operating business
GOOD_RATING = 15   # 4.0+ stars -> cares about reputation/presence
REVIEW_TIERS = (   # more reviews -> more revenue to justify the spend
    (200, 20, "200+ reviews — substantial revenue to justify a site"),
    (50, 12, "50+ reviews — solid customer volume"),
    (10, 6, "10+ reviews — established traffic"),
)


def score_lead(lead: Lead) -> tuple[int, list[str]]:
    """Return (0-100 score, reasons). Pure."""
    # HARD GATE: already has a website -> not a target at all.
    if lead.has_website:
        return 0, ["has website — not a target"]

    score = BASE
    reasons = [f"no website — base target (+{BASE})"]

    # Reachable by phone -> we can pitch.
    if lead.phone:
        score += PHONE_PTS
        reasons.append(f"has phone — reachable (+{PHONE_PTS})")

    # Has any reviews at all -> real operating business.
    reviews = lead.reviews or 0
    if reviews > 0:
        score += HAS_REVIEWS
        reasons.append(f"has reviews — established business (+{HAS_REVIEWS})")

    # More reviews -> more revenue -> more budget for a site. First tier hit wins.
    for threshold, pts, text in REVIEW_TIERS:
        if reviews >= threshold:
            score += pts
            reasons.append(f"{text} (+{pts})")
            break

    # Decent rating -> cares about reputation, likely to value online presence.
    if lead.rating is not None and lead.rating >= 4.0:
        score += GOOD_RATING
        reasons.append(f"rating {lead.rating:.1f} (4.0+) — cares about presence (+{GOOD_RATING})")

    score = max(0, min(100, score))  # cap 0-100
    return score, reasons
