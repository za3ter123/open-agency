import unittest

from . import _pathshim  # noqa: F401  (adds projects/agency to sys.path)
from leadengine.enrich import rewrite_photo_url, slugify


class TestSlugify(unittest.TestCase):
    def test_basic_name(self):
        self.assertEqual(slugify("Acme Plumbing Co"), "acme-plumbing-co")

    def test_strips_punctuation(self):
        self.assertEqual(slugify("Joe's Pizza & Grill!"), "joe-s-pizza-grill")

    def test_strips_leading_trailing_dashes(self):
        self.assertEqual(slugify("  --Hello World--  "), "hello-world")

    def test_empty_name(self):
        self.assertEqual(slugify(""), "")


class TestRewritePhotoUrl(unittest.TestCase):
    def test_rewrites_size_suffix(self):
        url = "https://lh3.googleusercontent.com/p/AF1QipX=w408-h306-k-no"
        self.assertEqual(
            rewrite_photo_url(url),
            "https://lh3.googleusercontent.com/p/AF1QipX=w1200",
        )

    def test_leaves_url_unchanged_without_match(self):
        url = "https://lh3.googleusercontent.com/p/AF1QipX"
        self.assertEqual(rewrite_photo_url(url), url)

    def test_leaves_non_size_query_unchanged(self):
        url = "https://example.com/photo.jpg"
        self.assertEqual(rewrite_photo_url(url), url)


if __name__ == "__main__":
    unittest.main()
