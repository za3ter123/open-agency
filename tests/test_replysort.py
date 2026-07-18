"""Tests for leadengine.replysort — pure reply classification."""
import unittest

from . import _pathshim  # noqa: F401
from leadengine.replysort import classify_reply


class TestClassifyReply(unittest.TestCase):
    def test_interested_question(self):
        self.assertEqual(classify_reply("How much does this cost?"), "interested")

    def test_interested_positive_statement(self):
        self.assertEqual(
            classify_reply("Yes, I'm interested, let's talk this week."), "interested"
        )

    def test_interested_call_me(self):
        self.assertEqual(classify_reply("Sounds good, call me tomorrow."), "interested")

    def test_rejected_unsubscribe(self):
        self.assertEqual(classify_reply("Please unsubscribe me from this list."), "rejected")

    def test_rejected_not_interested(self):
        self.assertEqual(classify_reply("Not interested, thanks."), "rejected")

    def test_rejected_bare_no(self):
        self.assertEqual(classify_reply("No."), "rejected")

    def test_auto_reply_out_of_office(self):
        self.assertEqual(
            classify_reply("I am currently out of the office until Monday."), "auto_reply"
        )

    def test_auto_reply_mailer_daemon(self):
        self.assertEqual(
            classify_reply("Delivery has failed for the following recipients."), "auto_reply"
        )

    def test_other_when_no_signal(self):
        self.assertEqual(classify_reply("Thanks for reaching out, will discuss internally."), "other")

    def test_empty_body_is_other(self):
        self.assertEqual(classify_reply(""), "other")
        self.assertEqual(classify_reply(None), "other")

    def test_auto_reply_wins_over_interested_keyword(self):
        # "call" collides with an interested-style phrase but out-of-office wins
        text = "Auto-reply: I'm on vacation, will respond when I'm back."
        self.assertEqual(classify_reply(text), "auto_reply")

    def test_rejected_wins_over_interested_keyword(self):
        text = "Not interested, please stop contacting us."
        self.assertEqual(classify_reply(text), "rejected")

    def test_case_insensitive(self):
        self.assertEqual(classify_reply("UNSUBSCRIBE ME NOW"), "rejected")


if __name__ == "__main__":
    unittest.main()
