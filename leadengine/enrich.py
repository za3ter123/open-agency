"""Enrich one lead from its Google Maps place page via the `agent-browser` CLI.

Pulls description/hours/reviews/photos/address off the place detail panel
with one defensive `eval`, downloads a few photos locally, and (via the CLI)
persists the result into the CRM through `crm.save_enrichment`.

Reuses `_run`/`_parse_eval` from scrape_maps.py — same agent-browser plumbing,
same JSON.stringify-then-double-decode convention.

Reproduce by hand:

    agent-browser open "<maps_url>"; agent-browser wait 3000
    agent-browser eval "<_ENRICH_JS>"   # -> {description, hours, reviews, ...}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

from .scrape_maps import _parse_eval, _run

# Every selector optional/defensive; page markup is unstable and locale-dependent.
_ENRICH_JS = r"""
(() => {
  const text = (el) => (el ? (el.textContent || '').trim() : '');

  let description = '';
  const editorial = document.querySelector('div[jsaction*="pane"] .PYvSYb')
                  || document.querySelector('div[jsaction*="pane"] editorial span');
  if (editorial) description = text(editorial);
  if (!description) {
    const meta = document.querySelector('meta[property="og:description"]');
    if (meta) description = meta.getAttribute('content') || '';
  }

  let hours = [];
  const hoursTable = document.querySelector('table[aria-label*="Hour"], table[aria-label*="hour"]')
                   || document.querySelector('div[aria-label*="Hour"], div[aria-label*="hour"]');
  if (hoursTable) {
    hoursTable.querySelectorAll('tr').forEach(row => {
      const t = (row.innerText || '').replace(/\s+/g, ' ').trim();
      if (t) hours.push(t);
    });
  }
  if (!hours.length) {
    document.querySelectorAll('table tr').forEach(row => {
      const t = (row.innerText || '').replace(/\s+/g, ' ').trim();
      if (t) hours.push(t);
    });
  }

  const reviews = [];
  document.querySelectorAll('span.wiI7pd').forEach(el => {
    if (reviews.length >= 5) return;
    const t = text(el);
    if (t) reviews.push(t);
  });

  const photoUrls = [];
  const seen = new Set();
  const addImg = (img) => {
    const src = img.getAttribute('src') || '';
    if (src && src.includes('googleusercontent') && !seen.has(src)) {
      seen.add(src);
      photoUrls.push(src);
    }
  };
  document.querySelectorAll('button[jsaction*="heroHeaderImage"] img').forEach(addImg);
  document.querySelectorAll('img[src*="googleusercontent"]').forEach(addImg);

  let addressFull = '';
  const addrBtn = document.querySelector('button[data-item-id="address"]');
  if (addrBtn) {
    addressFull = addrBtn.getAttribute('aria-label') || text(addrBtn);
  }

  return JSON.stringify({
    description, hours, reviews,
    photo_urls: photoUrls.slice(0, 12),
    address_full: addressFull,
  });
})()
"""

_PHOTO_SIZE_RE = re.compile(r"=w\d+-h\d+\S*$")


def slugify(name: str) -> str:
    """Lowercase, non-alnum -> '-', strip leading/trailing dashes."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower())
    return s.strip("-")


def rewrite_photo_url(url: str) -> str:
    """Swap a googleusercontent `=w###-h###...` size suffix for `=w1200`
    (a larger, uncropped fetch). Leaves the URL untouched if no match."""
    if _PHOTO_SIZE_RE.search(url):
        return _PHOTO_SIZE_RE.sub("=w1200", url)
    return url


def _download_photos(urls: list[str], out_dir: str, max_photos: int) -> list[str]:
    """Download up to max_photos URLs into out_dir/assets/photo_N.jpg.
    Failures are skipped silently (noted on stderr); returns relative paths."""
    assets_dir = os.path.join(out_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    saved: list[str] = []
    for i, url in enumerate(urls[:max_photos]):
        dest = os.path.join(assets_dir, f"photo_{i}.jpg")
        try:
            req = urllib.request.Request(
                rewrite_photo_url(url),
                headers={"User-Agent": "Mozilla/5.0 (leadengine enrich)"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            with open(dest, "wb") as f:
                f.write(data)
            saved.append(os.path.join("assets", f"photo_{i}.jpg"))
        except Exception as e:  # noqa: BLE001 - never let one bad photo crash enrich
            print(f"[enrich] photo {i} download failed: {e}", file=sys.stderr)
    return saved


def enrich_lead(maps_url: str, out_dir: str, max_photos: int = 6) -> dict:
    """Open the Maps place page and pull description/hours/reviews/photos."""
    _run(["open", maps_url])
    _run(["wait", "3000"])
    data = _parse_eval(_run(["eval", _ENRICH_JS], timeout=30))
    data = data if isinstance(data, dict) else {}

    photo_urls = [u for u in (data.get("photo_urls") or []) if isinstance(u, str)]
    photos = _download_photos(photo_urls, out_dir, max_photos)

    return {
        "description": data.get("description") or "",
        "hours": data.get("hours") or [],
        "reviews": data.get("reviews") or [],
        "photos": photos,
        "photo_urls": photo_urls,
        "address_full": data.get("address_full") or "",
        "enriched_at": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    from . import crm  # lazy: crm.py may not exist at import time of this module
    from .store import init_db

    p = argparse.ArgumentParser(prog="leadengine.enrich", description=__doc__)
    p.add_argument("dedupe_key", help="dedupe_key of the lead to enrich")
    p.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "..", "leads.db"),
                    help="SQLite CRM path (same default as cli.py)")
    p.add_argument("--sites-root", default=os.path.join(os.path.dirname(__file__), "..", "sites"),
                    help="root dir for per-lead site output")
    p.add_argument("--max-photos", type=int, default=6, help="max photos to download (default 6)")
    args = p.parse_args(argv)

    conn = init_db(args.db)
    crm.init_pipeline(conn)

    row = conn.execute(
        "SELECT * FROM leads WHERE dedupe_key = ?", (args.dedupe_key,)
    ).fetchone()
    if row is None:
        print(f"[enrich] no lead with dedupe_key={args.dedupe_key!r}", file=sys.stderr)
        conn.close()
        return 2
    lead = dict(row)
    maps_url = lead.get("maps_url")
    if not maps_url:
        print(f"[enrich] lead {args.dedupe_key!r} has no maps_url", file=sys.stderr)
        conn.close()
        return 2

    slug = slugify(lead.get("name", ""))
    out_dir = os.path.join(args.sites_root, slug)
    os.makedirs(out_dir, exist_ok=True)

    data = enrich_lead(maps_url, out_dir, max_photos=args.max_photos)
    crm.save_enrichment(conn, args.dedupe_key, data)
    conn.close()

    print(json.dumps({"dedupe_key": args.dedupe_key, "slug": slug, **data}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
