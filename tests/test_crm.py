import os
import tempfile
import unittest

from . import _pathshim  # noqa: F401  (adds projects/agency to sys.path)
from leadengine.store import init_db
from leadengine.crm import (
    init_pipeline, ensure_row, get_stage, set_stage, save_enrichment,
    set_site, set_qa, set_email, record_touch, due_followups, pipeline_row,
    board,
)

DAY0 = "2026-01-01T00:00:00+00:00"


def _iso(day: int) -> str:
    return f"2026-01-{1 + day:02d}T00:00:00+00:00"


class TestCrm(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = init_db(self.path)
        init_pipeline(self.conn)
        self.key = "acme co|5125550100"

    def tearDown(self):
        self.conn.close()
        os.unlink(self.path)

    # -- stage machine --------------------------------------------------

    def test_ensure_row_defaults_to_new(self):
        ensure_row(self.conn, self.key)
        self.assertEqual(get_stage(self.conn, self.key), "new")

    def test_valid_transition_chain(self):
        for stage in ["enriched", "built", "qa_passed", "deployed", "pitched"]:
            set_stage(self.conn, self.key, stage)
            self.assertEqual(get_stage(self.conn, self.key), stage)

    def test_invalid_transition_raises(self):
        with self.assertRaises(ValueError):
            set_stage(self.conn, self.key, "deployed")  # new -> deployed skips steps

    def test_unknown_stage_raises(self):
        with self.assertRaises(ValueError):
            set_stage(self.conn, self.key, "bogus")

    def test_any_stage_to_dead_allowed(self):
        set_stage(self.conn, self.key, "enriched")
        set_stage(self.conn, self.key, "dead")
        self.assertEqual(get_stage(self.conn, self.key), "dead")

    def test_follow_up_self_loop_allowed(self):
        set_stage(self.conn, self.key, "enriched")
        set_stage(self.conn, self.key, "built")
        set_stage(self.conn, self.key, "qa_passed")
        set_stage(self.conn, self.key, "deployed")
        set_stage(self.conn, self.key, "pitched")
        set_stage(self.conn, self.key, "follow_up")
        set_stage(self.conn, self.key, "follow_up")  # no-op re-entry, must not raise
        self.assertEqual(get_stage(self.conn, self.key), "follow_up")

    # -- enrichment / site / qa -----------------------------------------

    def test_save_enrichment_bumps_new_to_enriched(self):
        save_enrichment(self.conn, self.key, {"industry": "plumbing"})
        self.assertEqual(get_stage(self.conn, self.key), "enriched")
        row = pipeline_row(self.conn, self.key)
        self.assertEqual(row["enriched_json"], {"industry": "plumbing"})

    def test_save_enrichment_does_not_rewind_later_stage(self):
        set_stage(self.conn, self.key, "enriched")
        set_stage(self.conn, self.key, "built")
        save_enrichment(self.conn, self.key, {"industry": "plumbing"})
        self.assertEqual(get_stage(self.conn, self.key), "built")

    def test_set_site_stores_fields_without_changing_stage(self):
        set_site(self.conn, self.key, "/tmp/site", site_url="https://x.example")
        row = pipeline_row(self.conn, self.key)
        self.assertEqual(row["site_dir"], "/tmp/site")
        self.assertEqual(row["site_url"], "https://x.example")
        self.assertEqual(row["stage"], "new")

    def test_set_qa_pass_advances_stage(self):
        set_stage(self.conn, self.key, "enriched")
        set_stage(self.conn, self.key, "built")
        set_qa(self.conn, self.key, {"lighthouse": 95}, passed=True)
        self.assertEqual(get_stage(self.conn, self.key), "qa_passed")

    def test_set_qa_fail_keeps_stage_built(self):
        set_stage(self.conn, self.key, "enriched")
        set_stage(self.conn, self.key, "built")
        set_qa(self.conn, self.key, {"lighthouse": 40}, passed=False)
        self.assertEqual(get_stage(self.conn, self.key), "built")
        row = pipeline_row(self.conn, self.key)
        self.assertEqual(row["qa_report"], {"lighthouse": 40})

    def test_set_email(self):
        set_email(self.conn, self.key, "owner@example.com")
        row = pipeline_row(self.conn, self.key)
        self.assertEqual(row["email"], "owner@example.com")

    # -- touches ----------------------------------------------------------

    def _to_deployed(self):
        set_stage(self.conn, self.key, "enriched")
        set_stage(self.conn, self.key, "built")
        set_stage(self.conn, self.key, "qa_passed")
        set_stage(self.conn, self.key, "deployed")

    def test_touch_1_sets_pitched(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "subj", "body", sent_at=DAY0)
        self.assertEqual(get_stage(self.conn, self.key), "pitched")

    def test_touch_2_sets_follow_up(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "subj", "body", sent_at=DAY0)
        record_touch(self.conn, self.key, 2, "s2", "b2", sent_at=_iso(2))
        self.assertEqual(get_stage(self.conn, self.key), "follow_up")

    def test_duplicate_touch_no_is_ignored_not_raised(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "subj", "body", sent_at=DAY0)
        # Same touch_no again (e.g. a retried send) must not raise and
        # must not double-insert or re-run the stage transition.
        record_touch(self.conn, self.key, 1, "subj2", "body2", sent_at=_iso(1))
        rows = self.conn.execute(
            "SELECT COUNT(*) AS n FROM touches WHERE dedupe_key = ?", (self.key,)
        ).fetchone()
        self.assertEqual(rows["n"], 1)
        # original subject preserved (INSERT OR IGNORE keeps first row)
        row = self.conn.execute(
            "SELECT subject FROM touches WHERE dedupe_key = ? AND touch_no = 1",
            (self.key,),
        ).fetchone()
        self.assertEqual(row["subject"], "subj")

    # -- due_followups ------------------------------------------------------

    def test_nothing_due_day_after_pitch(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "s", "b", sent_at=DAY0)
        due = due_followups(self.conn, now=_iso(1))
        self.assertEqual(due, [])

    def test_touch_2_due_at_day_2(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "s", "b", sent_at=DAY0)
        due = due_followups(self.conn, now=_iso(2))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["dedupe_key"], self.key)
        self.assertEqual(due[0]["next_touch_no"], 2)

    def test_touch_3_due_at_day_5_after_touch_2_sent(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "s", "b", sent_at=DAY0)
        record_touch(self.conn, self.key, 2, "s2", "b2", sent_at=_iso(2))
        # not yet due at day 4
        self.assertEqual(due_followups(self.conn, now=_iso(4)), [])
        due = due_followups(self.conn, now=_iso(5))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["next_touch_no"], 3)

    def test_due_followups_caps_at_5_touches(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "s", "b", sent_at=DAY0)
        record_touch(self.conn, self.key, 2, "s", "b", sent_at=_iso(2))
        record_touch(self.conn, self.key, 3, "s", "b", sent_at=_iso(5))
        record_touch(self.conn, self.key, 4, "s", "b", sent_at=_iso(9))
        record_touch(self.conn, self.key, 5, "s", "b", sent_at=_iso(14))
        # 5 touches already sent -> nothing further ever due
        due = due_followups(self.conn, now=_iso(30))
        self.assertEqual(due, [])

    def test_due_followups_stops_after_reply(self):
        self._to_deployed()
        record_touch(self.conn, self.key, 1, "s", "b", sent_at=DAY0)
        set_stage(self.conn, self.key, "replied")
        due = due_followups(self.conn, now=_iso(30))
        self.assertEqual(due, [])

    # -- board --------------------------------------------------------------

    def test_board_groups_by_stage(self):
        ensure_row(self.conn, self.key)
        b = board(self.conn)
        self.assertIn("new", b)
        self.assertEqual(len(b["new"]), 1)
        self.assertEqual(b["new"][0]["dedupe_key"], self.key)


if __name__ == "__main__":
    unittest.main()
