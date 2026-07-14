import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from . import _pathshim  # noqa: F401  (adds projects/agency to sys.path)
from leadengine.outreach import load_env, send_email, _from_header


class TestLoadEnv(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".env")
        os.close(fd)

    def tearDown(self):
        os.unlink(self.path)

    def _write(self, text: str) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_parses_key_value_pairs(self):
        self._write("SMTP_HOST=smtp.example.com\nSMTP_USER=me@example.com\n")
        cfg = load_env(self.path)
        self.assertEqual(cfg["SMTP_HOST"], "smtp.example.com")
        self.assertEqual(cfg["SMTP_USER"], "me@example.com")

    def test_ignores_blank_and_comment_lines(self):
        self._write("\n# a comment\nSMTP_HOST=host\n\n# another\n")
        cfg = load_env(self.path)
        self.assertEqual(cfg["SMTP_HOST"], "host")
        self.assertEqual(len([k for k in cfg if k.startswith("#")]), 0)

    def test_strips_surrounding_quotes(self):
        self._write('SMTP_PASS="s3cret"\nFROM_NAME=\'Acme Co\'\n')
        cfg = load_env(self.path)
        self.assertEqual(cfg["SMTP_PASS"], "s3cret")
        self.assertEqual(cfg["FROM_NAME"], "Acme Co")

    def test_missing_file_returns_defaults_only(self):
        cfg = load_env("does/not/exist.env")
        self.assertEqual(cfg["SMTP_PORT"], "587")
        self.assertNotIn("SMTP_HOST", cfg)

    def test_default_port_and_from_email_applied(self):
        self._write("SMTP_USER=me@example.com\n")
        cfg = load_env(self.path)
        self.assertEqual(cfg["SMTP_PORT"], "587")
        self.assertEqual(cfg["FROM_EMAIL"], "me@example.com")

    def test_never_exposes_smtp_pass_key_absent_when_unset(self):
        self._write("SMTP_HOST=host\n")
        cfg = load_env(self.path)
        self.assertNotIn("SMTP_PASS", cfg)


class TestFromHeader(unittest.TestCase):
    def test_with_name(self):
        cfg = {"FROM_EMAIL": "me@example.com", "FROM_NAME": "Acme Co"}
        self.assertEqual(_from_header(cfg), "Acme Co <me@example.com>")

    def test_without_name(self):
        cfg = {"FROM_EMAIL": "me@example.com", "FROM_NAME": ""}
        self.assertEqual(_from_header(cfg), "me@example.com")


class TestSendEmailDryRun(unittest.TestCase):
    def test_dry_run_prints_and_returns_true_without_smtp(self):
        cfg = {
            "DRY_RUN": "1",
            "SMTP_HOST": "",
            "FROM_EMAIL": "me@example.com",
            "FROM_NAME": "Acme Co",
        }
        with mock.patch("smtplib.SMTP", side_effect=AssertionError("must not be called")), \
             mock.patch("smtplib.SMTP_SSL", side_effect=AssertionError("must not be called")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = send_email(cfg, "lead@example.com", "Hi", "body text")
        self.assertTrue(result)
        out = buf.getvalue()
        self.assertIn("lead@example.com", out)
        self.assertIn("Acme Co <me@example.com>", out)
        self.assertIn("body text", out)

    def test_dry_run_truthy_variants(self):
        for val in ("true", "yes", "1", "on"):
            cfg = {"DRY_RUN": val, "SMTP_HOST": ""}
            with redirect_stdout(io.StringIO()):
                self.assertTrue(send_email(cfg, "a@b.com", "s", "b"))

    def test_dry_run_falsy_does_not_short_circuit(self):
        # DRY_RUN unset/false + bad host -> real send attempted -> fails cleanly
        cfg = {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": "1", "SMTP_USER": "u", "SMTP_PASS": "p"}
        with mock.patch("smtplib.SMTP", side_effect=OSError("connection refused")):
            with redirect_stdout(io.StringIO()):
                result = send_email(cfg, "a@b.com", "s", "b")
        self.assertFalse(result)


class TestSendEmailFailurePath(unittest.TestCase):
    def test_smtp_exception_returns_false_without_raising(self):
        cfg = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "u",
            "SMTP_PASS": "p",
        }
        with mock.patch("smtplib.SMTP", side_effect=OSError("boom")):
            try:
                result = send_email(cfg, "a@b.com", "s", "b")
            except Exception as e:  # pragma: no cover - test fails via assert below
                self.fail(f"send_email raised {e!r} instead of returning False")
        self.assertFalse(result)

    def test_ssl_port_uses_smtp_ssl(self):
        cfg = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "465",
            "SMTP_USER": "u",
            "SMTP_PASS": "p",
        }
        with mock.patch("smtplib.SMTP_SSL", side_effect=OSError("boom")) as ssl_mock, \
             mock.patch("smtplib.SMTP", side_effect=AssertionError("must not use plain SMTP")):
            result = send_email(cfg, "a@b.com", "s", "b")
        self.assertFalse(result)
        self.assertTrue(ssl_mock.called)


if __name__ == "__main__":
    unittest.main()
