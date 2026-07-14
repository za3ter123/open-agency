import unittest

from . import _pathshim  # noqa: F401  (adds projects/agency to sys.path)
from leadengine.models import Lead
from leadengine.score import score_lead


def _lead(**kw):
    base = dict(
        name="Acme Co", category="plumber", address="1 Main St",
        phone="512-555-0100", rating=4.6, reviews=120,
        has_website=False, maps_url=None,
    )
    base.update(kw)
    return Lead(**base)


class TestScore(unittest.TestCase):
    def test_has_website_gate_returns_zero(self):
        score, reasons = score_lead(_lead(has_website=True))
        self.assertEqual(score, 0)
        self.assertIn("has website — not a target", reasons)

    def test_rich_lead_beats_bare_lead(self):
        rich = score_lead(_lead(phone="512-555-0100", reviews=300, rating=4.8))[0]
        bare = score_lead(_lead(phone=None, reviews=0, rating=None))[0]
        self.assertGreater(rich, bare)

    def test_score_capped_0_100(self):
        for lead in (
            _lead(reviews=99999, rating=5.0),     # max signals
            _lead(phone=None, reviews=0, rating=None),  # min signals
            _lead(has_website=True),               # gated
        ):
            score, _ = score_lead(lead)
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_deterministic(self):
        lead = _lead(reviews=57, rating=4.2)
        a = score_lead(lead)
        b = score_lead(lead)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
