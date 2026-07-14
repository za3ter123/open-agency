import os
import tempfile
import unittest
from unittest import mock

from . import _pathshim  # noqa: F401  (adds projects/agency to sys.path)
from leadengine.deploy import detect_providers, deploy_site


class TestDetectProviders(unittest.TestCase):
    def test_returns_dict_of_bools(self):
        detected = detect_providers()
        self.assertEqual(set(detected), {"gh", "vercel", "netlify", "wrangler"})
        for v in detected.values():
            self.assertIsInstance(v, bool)


class TestDeploySiteLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "index.html"), "w", encoding="utf-8") as f:
            f.write("<html></html>")

    def test_local_returns_file_url(self):
        url = deploy_site(self.tmp, "acme", provider="local")
        self.assertTrue(url.startswith("file://"))
        self.assertTrue(url.endswith("index.html"))


class TestDeploySiteSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "index.html"), "w", encoding="utf-8") as f:
            f.write("<html></html>")

    def test_non_local_without_yes_raises(self):
        with self.assertRaises(RuntimeError):
            deploy_site(self.tmp, "acme", provider="gh-pages", yes=False)

    def test_gh_pages_without_gh_installed_raises(self):
        with mock.patch("leadengine.deploy.shutil.which", return_value=None), \
             mock.patch("leadengine.deploy.subprocess.run") as run:
            with self.assertRaises(RuntimeError) as ctx:
                deploy_site(self.tmp, "acme", provider="gh-pages", yes=True)
            self.assertIn("gh", str(ctx.exception))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
