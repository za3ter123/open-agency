"""Lead data model + dedupe key."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Lead:
    """A single local-business lead scraped from a maps source."""

    name: str
    category: str
    address: str
    phone: str | None
    rating: float | None
    reviews: int | None
    has_website: bool
    maps_url: str | None
    source: str = "google_maps"

    def dedupe_key(self) -> str:
        """Stable identity key for dedupe.

        Prefer normalized name + digits-only phone (phone is the strongest
        cross-source identifier). Fall back to name + address when no phone.
        """
        name = _norm(self.name)
        digits = re.sub(r"\D", "", self.phone or "")
        if digits:
            return f"{name}|{digits}"
        return f"{name}|{_norm(self.address)}"


def _norm(s: str) -> str:
    """Lowercase + collapse whitespace for stable keys."""
    return re.sub(r"\s+", " ", (s or "").strip().lower())
