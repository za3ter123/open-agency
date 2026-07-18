"""Round-robin niche/region queue for continuous unattended runs.

    python -m leadengine.runqueue next    # print + advance to the next combo

Reads/writes `niches` (list), `regions` (list), and `queue_cursor` (int) in
config.json, alongside whatever wizard.py already keeps there. Named
runqueue (not queue) to avoid shadowing the stdlib `queue` module.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_DEFAULT_CONFIG = os.path.join(os.path.dirname(__file__), "..", "config.json")


def advance_cursor(niches: list[str], regions: list[str], cursor: int) -> tuple[str, str, int]:
    """Pure round-robin: pick the next (niche, region) combo from the
    cartesian product of niches x regions, ordered niche-major, and return
    it with the advanced cursor (wraps at the end). Raises ValueError if
    either list is empty.
    """
    if not niches or not regions:
        raise ValueError("both niches and regions must be non-empty")
    combos = [(n, r) for n in niches for r in regions]
    cursor = cursor % len(combos)
    niche, region = combos[cursor]
    next_cursor = (cursor + 1) % len(combos)
    return niche, region, next_cursor


def _load_config(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(path: str, config: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def next_combo(config_path: str = _DEFAULT_CONFIG) -> dict:
    """Read config.json, advance the cursor, persist it, and return the
    chosen {"niche", "region"} combo."""
    config = _load_config(config_path)
    niches = config.get("niches") or []
    regions = config.get("regions") or []
    cursor = config.get("queue_cursor", 0)

    niche, region, next_cursor = advance_cursor(niches, regions, cursor)

    config["queue_cursor"] = next_cursor
    _save_config(config_path, config)
    return {"niche": niche, "region": region}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leadengine.runqueue", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    nxt = sub.add_parser("next", help="print the next niche/region combo and advance the cursor")
    nxt.add_argument("--config", default=_DEFAULT_CONFIG)
    args = p.parse_args(argv)

    if args.command == "next":
        try:
            combo = next_combo(args.config)
        except ValueError as e:
            print(f"[runqueue] {e}", file=sys.stderr)
            return 2
        print(f"{combo['niche']} in {combo['region']}")
        return 0
    return 2  # pragma: no cover - unreachable, subparsers required=True


if __name__ == "__main__":
    raise SystemExit(main())
