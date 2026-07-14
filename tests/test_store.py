import os
import tempfile
import unittest

from . import _pathshim  # noqa: F401  (adds projects/agency to sys.path)
from leadengine.models import Lead
from leadengine.score import score_lead
from leadengine.store import init_db, upsert_lead, all_leads, set_status


def _lead(name="Acme Co", phone="512-555-0100", **kw):
    base = dict(
        name=name, category="plumber", address="1 Main St", phone=phone,
        rating=4.6, reviews=120, has_website=False, maps_url=None,
    )
    base.update(kw)
    return Lead(**base)


class TestStore(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = init_db(self.path)

    def tearDown(self):
        self.conn.close()
        os.unlink(self.path)

    def _upsert(self, lead):
        score, reasons = score_lead(lead)
        upsert_lead(self.conn, lead, score, reasons)

    def test_upsert_twice_yields_one_row(self):
        lead = _lead()
        self._upsert(lead)
        self._upsert(lead)  # same dedupe_key
        rows = all_leads(self.conn)
        self.assertEqual(len(rows), 1)

    def test_status_preserved_on_rescrape(self):
        lead = _lead()
        self._upsert(lead)
        set_status(self.conn, lead.dedupe_key(), "contacted")
        self._upsert(lead)  # re-scrape must NOT reset status to 'new'
        rows = all_leads(self.conn)
        self.assertEqual(rows[0]["status"], "contacted")

    def test_order_by_score(self):
        # high: phone + 300 reviews + 4.8 ; low: no phone, no reviews, no rating
        self._upsert(_lead(name="High Co", phone="512-555-0001",
                           reviews=300, rating=4.8))
        self._upsert(_lead(name="Low Co", phone=None,
                           reviews=0, rating=None))
        rows = all_leads(self.conn, order_by_score=True)
        self.assertEqual(rows[0]["name"], "High Co")
        self.assertGreater(rows[0]["score"], rows[1]["score"])


if __name__ == "__main__":
    unittest.main()
