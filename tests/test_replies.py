"""Tests for leadengine.replies — IMAP reply detection (pure parts only;
the imaplib network call is a thin wrapper left untested)."""
import unittest

from . import _pathshim  # noqa: F401
from leadengine import crm, replies
from leadengine.store import init_db


def _seed_pitched(conn, key: str, email: str) -> None:
    """Walk a lead to 'pitched' with an email on file."""
    for stage in ("enriched", "built", "qa_passed", "deployed"):
        crm.set_stage(conn, key, stage)
    crm.set_email(conn, key, email)
    crm.record_touch(conn, key, 1, "hi", "body")


class TestImapHost(unittest.TestCase):
    def test_explicit_override_wins(self):
        cfg = {"IMAP_HOST": "mail.example.com", "SMTP_HOST": "smtp.gmail.com"}
        self.assertEqual(replies.imap_host(cfg), "mail.example.com")

    def test_derives_from_smtp_prefix(self):
        self.assertEqual(replies.imap_host({"SMTP_HOST": "smtp.gmail.com"}), "imap.gmail.com")

    def test_non_smtp_prefixed_host_passes_through(self):
        self.assertEqual(replies.imap_host({"SMTP_HOST": "mail.example.com"}), "mail.example.com")

    def test_empty_cfg_gives_empty(self):
        self.assertEqual(replies.imap_host({}), "")


class TestExtractSender(unittest.TestCase):
    def test_name_and_angle_brackets(self):
        self.assertEqual(replies.extract_sender("Bob Plumber <bob@acme.com>"), "bob@acme.com")

    def test_bare_address(self):
        self.assertEqual(replies.extract_sender("bob@acme.com"), "bob@acme.com")

    def test_lowercases(self):
        self.assertEqual(replies.extract_sender("Bob <BOB@Acme.COM>"), "bob@acme.com")

    def test_garbage_gives_empty(self):
        self.assertEqual(replies.extract_sender("not an address"), "")


class TestApplyReplies(unittest.TestCase):
    def setUp(self):
        self.conn = init_db(":memory:")
        crm.init_pipeline(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_marks_pitched_lead_replied(self):
        _seed_pitched(self.conn, "k1", "bob@acme.com")
        marked = replies.apply_replies(self.conn, ["bob@acme.com"])
        self.assertEqual(marked, ["k1"])
        self.assertEqual(crm.get_stage(self.conn, "k1"), "replied")

    def test_marks_follow_up_lead_replied(self):
        _seed_pitched(self.conn, "k1", "bob@acme.com")
        crm.record_touch(self.conn, "k1", 2, "again", "body")
        self.assertEqual(crm.get_stage(self.conn, "k1"), "follow_up")
        marked = replies.apply_replies(self.conn, ["bob@acme.com"])
        self.assertEqual(marked, ["k1"])
        self.assertEqual(crm.get_stage(self.conn, "k1"), "replied")

    def test_sender_match_is_case_insensitive(self):
        _seed_pitched(self.conn, "k1", "Bob@Acme.com")
        marked = replies.apply_replies(self.conn, ["bob@acme.com"])
        self.assertEqual(marked, ["k1"])

    def test_unknown_sender_ignored(self):
        _seed_pitched(self.conn, "k1", "bob@acme.com")
        self.assertEqual(replies.apply_replies(self.conn, ["stranger@x.com"]), [])
        self.assertEqual(crm.get_stage(self.conn, "k1"), "pitched")

    def test_already_replied_is_idempotent(self):
        _seed_pitched(self.conn, "k1", "bob@acme.com")
        replies.apply_replies(self.conn, ["bob@acme.com"])
        # second run: lead no longer in pitched/follow_up, so no-op
        self.assertEqual(replies.apply_replies(self.conn, ["bob@acme.com"]), [])
        self.assertEqual(crm.get_stage(self.conn, "k1"), "replied")

    def test_lead_without_email_never_matches(self):
        for stage in ("enriched", "built", "qa_passed", "deployed"):
            crm.set_stage(self.conn, "k2", stage)
        self.assertEqual(replies.apply_replies(self.conn, ["bob@acme.com"]), [])

    def test_multiple_senders_multiple_leads(self):
        _seed_pitched(self.conn, "k1", "a@x.com")
        _seed_pitched(self.conn, "k2", "b@y.com")
        _seed_pitched(self.conn, "k3", "c@z.com")
        marked = replies.apply_replies(self.conn, ["b@y.com", "c@z.com", "noone@q.com"])
        self.assertEqual(sorted(marked), ["k2", "k3"])
        self.assertEqual(crm.get_stage(self.conn, "k1"), "pitched")


class TestSortReplies(unittest.TestCase):
    def setUp(self):
        self.conn = init_db(":memory:")
        crm.init_pipeline(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_classifies_and_stores_bucket(self):
        _seed_pitched(self.conn, "k1", "bob@acme.com")
        messages = [{"sender": "bob@acme.com", "subject": "Re: site",
                     "body": "How much does this cost?"}]
        grouped = replies.sort_replies(self.conn, messages)
        self.assertEqual(len(grouped["interested"]), 1)
        self.assertEqual(grouped["interested"][0]["dedupe_key"], "k1")
        row = crm.pipeline_row(self.conn, "k1")
        self.assertEqual(row["reply_bucket"], "interested")

    def test_unknown_sender_skipped(self):
        _seed_pitched(self.conn, "k1", "bob@acme.com")
        messages = [{"sender": "stranger@x.com", "subject": "s", "body": "Not interested"}]
        grouped = replies.sort_replies(self.conn, messages)
        self.assertEqual(sum(len(v) for v in grouped.values()), 0)

    def test_already_replied_lead_still_classified(self):
        _seed_pitched(self.conn, "k1", "bob@acme.com")
        crm.set_stage(self.conn, "k1", "replied")
        messages = [{"sender": "bob@acme.com", "subject": "s", "body": "unsubscribe me"}]
        grouped = replies.sort_replies(self.conn, messages)
        self.assertEqual(grouped["rejected"][0]["dedupe_key"], "k1")

    def test_multiple_buckets_grouped_separately(self):
        _seed_pitched(self.conn, "k1", "a@x.com")
        _seed_pitched(self.conn, "k2", "b@y.com")
        messages = [
            {"sender": "a@x.com", "subject": "s", "body": "sounds good, call me"},
            {"sender": "b@y.com", "subject": "s", "body": "please unsubscribe"},
        ]
        grouped = replies.sort_replies(self.conn, messages)
        self.assertEqual(grouped["interested"][0]["dedupe_key"], "k1")
        self.assertEqual(grouped["rejected"][0]["dedupe_key"], "k2")


if __name__ == "__main__":
    unittest.main()
