import json
import os
import tempfile
import shutil
import unittest

from . import _pathshim  # noqa: F401  (adds projects/agency to sys.path)
from leadengine.wizard import main, parse_env, render_env, merge_gitignore


class TestParseRenderEnv(unittest.TestCase):
    def test_roundtrip(self):
        d = {"SMTP_HOST": "smtp.x.com", "SMTP_PORT": "587", "FROM_NAME": "Acme"}
        self.assertEqual(parse_env(render_env(d)), d)

    def test_preserves_unknown_keys(self):
        text = "SMTP_HOST=old.smtp.com\nUNKNOWN_KEY=keepme\n"
        parsed = parse_env(text)
        self.assertEqual(parsed["UNKNOWN_KEY"], "keepme")
        self.assertEqual(parsed["SMTP_HOST"], "old.smtp.com")
        # roundtrip through render preserves it too
        self.assertIn("UNKNOWN_KEY=keepme", render_env(parsed))

    def test_ignores_blank_lines_and_comments(self):
        text = "\n# a comment\nSMTP_USER=me@x.com\n\n"
        parsed = parse_env(text)
        self.assertEqual(parsed, {"SMTP_USER": "me@x.com"})


class TestMergeGitignore(unittest.TestCase):
    def test_appends_missing_lines_to_empty(self):
        result = merge_gitignore("", [".env", "data/", "sites/"])
        self.assertIn(".env", result.splitlines())
        self.assertIn("data/", result.splitlines())
        self.assertIn("sites/", result.splitlines())

    def test_preserves_existing_content(self):
        existing = "node_modules/\n*.pyc\n"
        result = merge_gitignore(existing, [".env", "data/", "sites/"])
        self.assertIn("node_modules/", result)
        self.assertIn("*.pyc", result)
        self.assertIn(".env", result)

    def test_idempotent_appends_only_missing(self):
        existing = "node_modules/\n.env\ndata/\n"
        result = merge_gitignore(existing, [".env", "data/", "sites/"])
        self.assertEqual(result.count(".env"), 1)
        self.assertEqual(result.count("data/"), 1)
        self.assertIn("sites/", result)
        # running again with an already-complete file changes nothing
        result2 = merge_gitignore(result, [".env", "data/", "sites/"])
        self.assertEqual(result, result2)


class TestWizardMain(unittest.TestCase):
    def setUp(self):
        self.base_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base_dir, ignore_errors=True)

    def _argv(self, **overrides):
        vals = {
            "smtp-host": "smtp.gmail.com",
            "smtp-port": "587",
            "smtp-user": "me@gmail.com",
            "smtp-pass": "secret123",
            "from-name": "Acme Agency",
            "from-email": "me@gmail.com",
            "reply-to": "sales@acme.com",
            "region": "austin tx",
            "provider": "local",
            "sender-signature": "-- Acme Agency",
        }
        vals.update(overrides)
        argv = []
        for k, v in vals.items():
            if v is None:
                continue
            argv += [f"--{k}", str(v)]
        argv.append("--yes")
        return argv

    def test_writes_env_config_and_gitignore(self):
        rc = main(self._argv(), base_dir=self.base_dir)
        self.assertEqual(rc, 0)

        env_path = os.path.join(self.base_dir, ".env")
        with open(env_path, "r", encoding="utf-8") as f:
            env = parse_env(f.read())
        self.assertEqual(env["SMTP_HOST"], "smtp.gmail.com")
        self.assertEqual(env["SMTP_PASS"], "secret123")
        self.assertEqual(env["FROM_EMAIL"], "me@gmail.com")
        self.assertEqual(env["REPLY_TO"], "sales@acme.com")

        config_path = os.path.join(self.base_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["region"], "austin tx")
        self.assertEqual(config["deploy_provider"], "local")
        self.assertEqual(config["signature"], "-- Acme Agency")
        self.assertIn("created_at", config)

        gitignore_path = os.path.join(self.base_dir, ".gitignore")
        with open(gitignore_path, "r", encoding="utf-8") as f:
            gitignore = f.read()
        for line in (".env", "data/", "sites/"):
            self.assertIn(line, gitignore.splitlines())

    def test_from_email_defaults_to_smtp_user_when_omitted(self):
        rc = main(self._argv(**{"from-email": None}), base_dir=self.base_dir)
        self.assertEqual(rc, 0)
        with open(os.path.join(self.base_dir, ".env"), encoding="utf-8") as f:
            env = parse_env(f.read())
        self.assertEqual(env["FROM_EMAIL"], "me@gmail.com")  # == smtp-user

    def test_rerun_reuses_existing_values_as_defaults(self):
        main(self._argv(), base_dir=self.base_dir)
        with open(os.path.join(self.base_dir, "config.json"), encoding="utf-8") as f:
            first_created_at = json.load(f)["created_at"]

        # second run: only override region, everything else via --yes falls
        # back to the values already on disk (not the hardcoded flag defaults)
        rc = main(["--region", "dallas tx", "--yes"], base_dir=self.base_dir)
        self.assertEqual(rc, 0)

        with open(os.path.join(self.base_dir, ".env"), encoding="utf-8") as f:
            env = parse_env(f.read())
        self.assertEqual(env["SMTP_HOST"], "smtp.gmail.com")  # preserved

        with open(os.path.join(self.base_dir, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["region"], "dallas tx")
        self.assertEqual(config["created_at"], first_created_at)  # preserved

    def test_preexisting_gitignore_is_only_appended_to(self):
        with open(os.path.join(self.base_dir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("node_modules/\n")
        main(self._argv(), base_dir=self.base_dir)
        with open(os.path.join(self.base_dir, ".gitignore"), encoding="utf-8") as f:
            content = f.read()
        self.assertIn("node_modules/", content)
        self.assertIn(".env", content)


if __name__ == "__main__":
    unittest.main()
