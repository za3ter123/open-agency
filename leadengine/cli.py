"""CLI: scrape -> score -> dedupe into SQLite CRM -> ranked table -> CSV.

    python -m leadengine.cli "<query>" --limit N --db <path> --export <csv>
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

from .scrape_maps import scrape_maps
from .score import score_lead
from .store import init_db, upsert_lead, all_leads

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "leads.db")


def _print_table(rows: list[dict]) -> None:
    """Print ranked no-website leads."""
    targets = [r for r in rows if not r["has_website"]]
    if not targets:
        print("No no-website leads found.")
        return
    print(f"\n{'SCORE':>5}  {'NAME':<34} {'PHONE':<16} {'RATING':>6} {'REVIEWS':>7}")
    print("-" * 74)
    for r in targets:
        rating = f"{r['rating']:.1f}" if r["rating"] is not None else "-"
        print(f"{r['score']:>5}  {(r['name'] or '')[:34]:<34} "
              f"{(r['phone'] or '-'):<16} {rating:>6} {(r['reviews'] or 0):>7}")
    print(f"\n{len(targets)} no-website target(s).")


def _export_csv(rows: list[dict], path: str) -> None:
    cols = ["score", "name", "category", "phone", "rating", "reviews",
            "address", "has_website", "maps_url", "status"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Exported {len(rows)} rows -> {path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leadengine", description=__doc__)
    p.add_argument("query", help='Maps search, e.g. "plumbers in austin tx"')
    p.add_argument("--limit", type=int, default=20, help="max results (default 20)")
    p.add_argument("--db", default=_DEFAULT_DB, help="SQLite CRM path")
    p.add_argument("--export", help="optional CSV export path")
    args = p.parse_args(argv)

    print(f"[cli] scraping: {args.query!r} (limit {args.limit})", file=sys.stderr)
    leads = scrape_maps(args.query, limit=args.limit)
    print(f"[cli] scraped {len(leads)} lead(s)", file=sys.stderr)

    conn = init_db(args.db)
    for lead in leads:
        score, reasons = score_lead(lead)
        upsert_lead(conn, lead, score, reasons)

    rows = all_leads(conn, order_by_score=True)
    _print_table(rows)
    if args.export:
        _export_csv(rows, args.export)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
