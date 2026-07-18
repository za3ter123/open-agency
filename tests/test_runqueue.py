"""Tests for leadengine.runqueue — round-robin niche/region queue."""
import json
import os
import tempfile
import unittest

from . import _pathshim  # noqa: F401
from leadengine.runqueue import advance_cursor, next_combo


class TestAdvanceCursor(unittest.TestCase):
    def test_first_call_returns_first_combo(self):
        niche, region, cursor = advance_cursor(["plumbers"], ["austin"], 0)
        self.assertEqual((niche, region), ("plumbers", "austin"))
        self.assertEqual(cursor, 0)  # only one combo -> wraps to itself

    def test_round_robins_across_regions_then_niches(self):
        niches = ["plumbers", "roofers"]
        regions = ["austin", "dallas"]
        # niche-major cartesian order: (plumbers,austin) (plumbers,dallas)
        # (roofers,austin) (roofers,dallas)
        seen = []
        cursor = 0
        for _ in range(4):
            niche, region, cursor = advance_cursor(niches, regions, cursor)
            seen.append((niche, region))
        self.assertEqual(seen, [
            ("plumbers", "austin"), ("plumbers", "dallas"),
            ("roofers", "austin"), ("roofers", "dallas"),
        ])

    def test_wraps_around_after_full_cycle(self):
        niches, regions = ["plumbers"], ["austin", "dallas"]
        _, _, c1 = advance_cursor(niches, regions, 0)
        niche, region, c2 = advance_cursor(niches, regions, c1)
        self.assertEqual((niche, region), ("plumbers", "dallas"))
        niche, region, c3 = advance_cursor(niches, regions, c2)
        self.assertEqual((niche, region), ("plumbers", "austin"))  # wrapped
        self.assertEqual(c3, 1)

    def test_empty_niches_raises(self):
        with self.assertRaises(ValueError):
            advance_cursor([], ["austin"], 0)

    def test_empty_regions_raises(self):
        with self.assertRaises(ValueError):
            advance_cursor(["plumbers"], [], 0)

    def test_out_of_range_cursor_is_normalized(self):
        niche, region, cursor = advance_cursor(["a"], ["x", "y"], 5)
        # 5 % 2 == 1 -> second combo
        self.assertEqual((niche, region), ("a", "y"))


class TestNextCombo(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)

    def tearDown(self):
        os.unlink(self.path)

    def _write_config(self, config: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(config, f)

    def test_persists_cursor_across_calls(self):
        self._write_config({"niches": ["plumbers"], "regions": ["austin", "dallas"]})
        first = next_combo(self.path)
        second = next_combo(self.path)
        self.assertEqual(first, {"niche": "plumbers", "region": "austin"})
        self.assertEqual(second, {"niche": "plumbers", "region": "dallas"})

    def test_preserves_other_config_keys(self):
        self._write_config({
            "niches": ["plumbers"], "regions": ["austin"],
            "signature": "Jane Doe", "deploy_provider": "local",
        })
        next_combo(self.path)
        with open(self.path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["signature"], "Jane Doe")
        self.assertEqual(saved["deploy_provider"], "local")
        self.assertIn("queue_cursor", saved)

    def test_missing_niches_raises(self):
        self._write_config({"regions": ["austin"]})
        with self.assertRaises(ValueError):
            next_combo(self.path)


if __name__ == "__main__":
    unittest.main()
