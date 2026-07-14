"""Scrape Google Maps via the `agent-browser` CLI (no playwright import).

Two phases:

1. LIST  — open the Maps search, scroll the results feed, pull every result
   card's name + place URL with one `eval`.
2. DRILL — open each place URL and read the *authoritative* detail-panel
   signals: `a[data-item-id="authority"]` (the website link → has_website),
   `button[data-item-id^="phone:tel:"]` (phone), rating/reviews, category.

Why the drill: the list cards only expose Directions/Call/Save — they never
show whether a business has a website, which is the whole point of this tool.
The detail panel does, via stable `data-item-id` attributes that are
locale-independent (the browser may render a non-English UI).

Reproduce by hand:

    URL='https://www.google.com/maps/search/plumbers+in+austin+tx'
    agent-browser open "$URL"; agent-browser wait 4000
    agent-browser scroll down 2000        # a few times
    agent-browser eval "<_LIST_JS>"        # -> [{name, maps_url, info}]
    # then per place:
    agent-browser open "<maps_url>"; agent-browser wait 2500
    agent-browser eval "<_DETAIL_JS>"      # -> {has_website, phone, rating,...}
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import quote_plus

from .models import Lead


def _resolve_ab() -> str:
    """Resolve the agent-browser executable. Prefer the native win32 exe that
    the npm `.CMD` shim wraps — calling it directly bypasses cmd.exe, which
    otherwise truncates multi-line JS args and chokes on `=>`/`||` metachars.
    Falls back to the shim path (works for simple args) then the bare name."""
    shim = shutil.which("agent-browser")
    if shim:
        exe = os.path.join(os.path.dirname(shim), "node_modules",
                           "agent-browser", "bin", "agent-browser-win32-x64.exe")
        return exe if os.path.exists(exe) else shim
    return "agent-browser"


_AB = _resolve_ab()

# Phase 1: list of result cards. Every selector is optional/defensive.
_LIST_JS = r"""
(() => {
  const out = [];
  const feed = document.querySelector('div[role="feed"]') || document;
  feed.querySelectorAll('a.hfpxzc').forEach(a => {
    const card = a.closest('div[role="article"]') || a.parentElement;
    const name = a.getAttribute('aria-label') || '';
    const href = a.getAttribute('href') || '';
    const info = card ? (card.innerText || '').replace(/\s+/g, ' ').trim() : '';
    if (name && href) out.push({ name, maps_url: href, info });
  });
  return JSON.stringify(out);
})()
"""

# Phase 2: authoritative detail-panel signals, keyed off stable data-item-id.
_DETAIL_JS = r"""
(() => {
  const authority = document.querySelector('a[data-item-id="authority"]');
  let phone = null;
  const pb = document.querySelector('button[data-item-id^="phone:tel:"]')
          || document.querySelector('button[data-item-id^="phone"]');
  if (pb) {
    const id = pb.getAttribute('data-item-id') || '';
    const m = id.match(/tel:(.+)$/);
    phone = m ? m[1] : null;
    if (!phone) {
      const a = pb.getAttribute('aria-label') || '';
      const mm = a.match(/[\d][\d\s().+-]{6,}\d/);
      phone = mm ? mm[0].trim() : null;
    }
  }
  let rating = null, reviews = null;
  const rt = (document.body.innerText || '').match(/(\d\.\d)\s*\(?\s*([\d,]{1,7})\s*\)?\s*review/i)
          || (document.body.innerText || '').match(/(\d\.\d)\D{0,4}\(([\d,]+)\)/);
  if (rt) { rating = parseFloat(rt[1]); reviews = parseInt(rt[2].replace(/,/g, ''), 10); }
  const catEl = document.querySelector('button[jsaction*="category"]');
  const category = catEl ? (catEl.textContent || '').trim() : '';
  return JSON.stringify({
    has_website: !!authority,
    website_url: authority ? authority.href : null,
    phone, rating, reviews, category
  });
})()
"""

_PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")
_RATING_RE = re.compile(r"(\d\.\d)\s*\(([\d,]+)\)")


def _run(args: list[str], timeout: int = 60) -> str:
    """Run agent-browser, return stdout. Never raises on tool failure."""
    try:
        r = subprocess.run(
            [_AB, *args],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        if r.returncode != 0:
            print(f"[scrape] agent-browser {args[0]} rc={r.returncode}: "
                  f"{r.stderr.strip()[:200]}", file=sys.stderr)
        return r.stdout
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[scrape] agent-browser {args[0]} failed: {e}", file=sys.stderr)
        return ""


def _parse_eval(raw: str) -> object:
    """agent-browser echoes the JS return value as a JSON-encoded string, so a
    JSON.stringify(...) result comes back double-encoded. Unwrap both layers."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, str):  # double-encoded
            data = json.loads(data)
        return data
    except json.JSONDecodeError:
        pass
    start, end = raw.find("["), raw.rfind("]")          # array fallback
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    start, end = raw.find("{"), raw.rfind("}")          # object fallback
    if start != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _parse_info(info: str) -> tuple[str, float | None, int | None]:
    """Best-effort category/rating/reviews from list card text (drill fills gaps)."""
    rating, reviews = None, None
    m = _RATING_RE.search(info)
    if m:
        rating = float(m.group(1))
        reviews = int(m.group(2).replace(",", ""))
    else:
        bm = re.search(r"\b([1-5]\.\d)\b", info)  # bare rating, no (count)
        if bm:
            rating = float(bm.group(1))
    category = ""
    for line in info.split("·"):
        line = line.strip()
        if line and not _RATING_RE.search(line) and not _PHONE_RE.search(line):
            category = line
            break
    return category, rating, reviews


def scrape_maps(query: str, limit: int = 20, drill: bool = True) -> list[Lead]:
    """Scrape up to `limit` Maps results for `query`.

    drill=True (default) opens each place to read the authoritative website /
    phone signals — required for has_website to be trustworthy. Resilient:
    partial/empty results never crash the caller.
    """
    leads: list[Lead] = []
    try:
        url = "https://www.google.com/maps/search/" + quote_plus(query)
        print(f"[scrape] opening {url}", file=sys.stderr)
        _run(["open", url])
        _run(["wait", "4000"])
        for i in range(3):
            _run(["scroll", "down", "2000"])
            _run(["wait", "1500"])
        items = _parse_eval(_run(["eval", _LIST_JS], timeout=30))
        items = items if isinstance(items, list) else []
        print(f"[scrape] {len(items)} cards in list; drilling {min(limit, len(items))}",
              file=sys.stderr)

        for it in items[:limit]:
            cat, rating, reviews = _parse_info(it.get("info", ""))
            phone, has_website = None, False
            maps_url = it.get("maps_url") or None
            if drill and maps_url:
                _run(["open", maps_url])
                _run(["wait", "2500"])
                d = _parse_eval(_run(["eval", _DETAIL_JS], timeout=30))
                if isinstance(d, dict):
                    has_website = bool(d.get("has_website", False))
                    phone = d.get("phone") or None
                    rating = d.get("rating") if d.get("rating") is not None else rating
                    reviews = d.get("reviews") if d.get("reviews") is not None else reviews
                    cat = d.get("category") or cat
                    print(f"[scrape]  {it.get('name','?')[:40]:40} "
                          f"website={has_website}", file=sys.stderr)
            leads.append(Lead(
                name=it.get("name", "").strip(),
                category=cat,
                address=it.get("info", "").strip()[:300],
                phone=phone,
                rating=rating,
                reviews=reviews,
                has_website=has_website,
                maps_url=maps_url,
            ))
    except Exception as e:  # never let scraping crash the caller
        print(f"[scrape] unexpected error, returning partial: {e}", file=sys.stderr)

    return leads
