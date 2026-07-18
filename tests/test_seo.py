"""Tests for leadengine.seo — pure SEO/go-live checklist audit."""
import os
import re
import tempfile
import unittest

from . import _pathshim  # noqa: F401
from leadengine.seo import audit_html, seo_pass, failed_checks, audit_site_dir

_GOOD_HTML = """
<!doctype html>
<html>
<head>
  <title>Acme Plumbing</title>
  <meta name="description" content="Local plumbing in Austin, TX.">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta property="og:title" content="Acme Plumbing">
  <meta property="og:description" content="Local plumbing in Austin, TX.">
  <meta property="og:image" content="og.png">
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"LocalBusiness","name":"Acme Plumbing"}
  </script>
</head>
<body>
  <h1>Acme Plumbing</h1>
  <img src="hero.jpg" alt="Acme Plumbing storefront">
  <a href="tel:+15125550100">Call us</a>
  <a href="https://www.google.com/maps?q=Acme+Plumbing">Find us</a>
</body>
</html>
"""


class TestAuditHtml(unittest.TestCase):
    def test_good_site_passes_every_check(self):
        results = audit_html(_GOOD_HTML)
        self.assertTrue(seo_pass(results))
        self.assertEqual(failed_checks(results), [])

    def test_missing_title_fails(self):
        html = _GOOD_HTML.replace("<title>Acme Plumbing</title>", "")
        results = audit_html(html)
        self.assertFalse(results["title"])
        self.assertFalse(seo_pass(results))

    def test_empty_title_fails(self):
        html = _GOOD_HTML.replace("<title>Acme Plumbing</title>", "<title></title>")
        self.assertFalse(audit_html(html)["title"])

    def test_missing_meta_description_fails(self):
        html = _GOOD_HTML.replace(
            '<meta name="description" content="Local plumbing in Austin, TX.">', ""
        )
        self.assertFalse(audit_html(html)["meta_description"])

    def test_missing_viewport_fails(self):
        html = _GOOD_HTML.replace(
            '<meta name="viewport" content="width=device-width, initial-scale=1">', ""
        )
        self.assertFalse(audit_html(html)["viewport"])

    def test_zero_h1_fails(self):
        html = _GOOD_HTML.replace("<h1>Acme Plumbing</h1>", "")
        self.assertFalse(audit_html(html)["single_h1"])

    def test_multiple_h1_fails(self):
        html = _GOOD_HTML.replace("<h1>Acme Plumbing</h1>", "<h1>A</h1><h1>B</h1>")
        self.assertFalse(audit_html(html)["single_h1"])

    def test_missing_og_tags_fail_individually(self):
        html = _GOOD_HTML.replace('<meta property="og:image" content="og.png">', "")
        results = audit_html(html)
        self.assertFalse(results["og_image"])
        self.assertTrue(results["og_title"])

    def test_missing_jsonld_local_business_fails(self):
        html = re.sub(
            r'<script type="application/ld\+json">.*?</script>', "", _GOOD_HTML, flags=re.DOTALL
        )
        self.assertFalse(audit_html(html)["jsonld_local_business"])

    def test_img_without_alt_fails(self):
        html = _GOOD_HTML.replace(
            '<img src="hero.jpg" alt="Acme Plumbing storefront">', '<img src="hero.jpg">'
        )
        self.assertFalse(audit_html(html)["img_alt"])

    def test_img_with_empty_alt_fails(self):
        html = _GOOD_HTML.replace(
            '<img src="hero.jpg" alt="Acme Plumbing storefront">', '<img src="hero.jpg" alt="">'
        )
        self.assertFalse(audit_html(html)["img_alt"])

    def test_no_images_passes_alt_check(self):
        html = _GOOD_HTML.replace('<img src="hero.jpg" alt="Acme Plumbing storefront">', "")
        self.assertTrue(audit_html(html)["img_alt"])

    def test_missing_tel_link_fails(self):
        html = _GOOD_HTML.replace('<a href="tel:+15125550100">Call us</a>', "")
        self.assertFalse(audit_html(html)["tel_link"])

    def test_maps_link_does_not_count_as_external_request(self):
        self.assertTrue(audit_html(_GOOD_HTML)["no_external_requests"])

    def test_external_script_fails(self):
        html = _GOOD_HTML.replace(
            "</head>", '<script src="https://cdn.example.com/x.js"></script></head>'
        )
        self.assertFalse(audit_html(html)["no_external_requests"])

    def test_empty_html_fails_overall(self):
        # img_alt and no_external_requests vacuously pass on empty markup
        # (no <img>, no external src/href) but every content check fails.
        results = audit_html("")
        self.assertFalse(seo_pass(results))
        self.assertTrue(results["img_alt"])
        self.assertTrue(results["no_external_requests"])
        self.assertFalse(results["title"])


class TestAuditSiteDir(unittest.TestCase):
    def test_reads_index_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
                f.write(_GOOD_HTML)
            results = audit_site_dir(tmp)
            self.assertTrue(seo_pass(results))

    def test_missing_index_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                audit_site_dir(tmp)


if __name__ == "__main__":
    unittest.main()
