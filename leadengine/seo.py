"""SEO / go-live audit for a generated site's index.html.

    python -m leadengine.seo <dedupe_key> [--db PATH]

Pure regex-based checklist (no third-party HTML parser). deploy.py calls
audit_html()/seo_pass() to gate gh-pages publishing on a clean audit.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "leads.db")

# Hosts allowed as external requests even though the "no external requests"
# check otherwise rejects any http(s) src/href — a Google Maps embed/link is
# expected on a local-business one-pager.
_ALLOWED_EXTERNAL_HOSTS = re.compile(
    r"https?://(www\.)?(google\.[a-z.]+/maps|goo\.gl/maps|maps\.google\.[a-z.]+)",
    re.IGNORECASE,
)

_CHECK_NAMES = [
    "title",
    "meta_description",
    "viewport",
    "single_h1",
    "og_title",
    "og_description",
    "og_image",
    "jsonld_local_business",
    "img_alt",
    "tel_link",
    "no_external_requests",
]


def _has_title(html: str) -> bool:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return bool(m and m.group(1).strip())


def _has_meta(html: str, name: str) -> bool:
    pattern = (
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']'
        rf'|<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:name|property)=["\']{re.escape(name)}["\']'
    )
    m = re.search(pattern, html, re.IGNORECASE)
    if not m:
        return False
    return bool((m.group(1) or m.group(2) or "").strip())


def _single_h1(html: str) -> bool:
    return len(re.findall(r"<h1\b", html, re.IGNORECASE)) == 1


def _has_jsonld_local_business(html: str) -> bool:
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.IGNORECASE | re.DOTALL,
    ):
        if "localbusiness" in m.group(1).lower():
            return True
    return False


def _all_img_have_alt(html: str) -> bool:
    imgs = re.findall(r"<img\b[^>]*>", html, re.IGNORECASE)
    if not imgs:
        return True
    for tag in imgs:
        m = re.search(r'alt=["\']([^"\']*)["\']', tag, re.IGNORECASE)
        if not m or not m.group(1).strip():
            return False
    return True


def _has_tel_link(html: str) -> bool:
    return bool(re.search(r'href=["\']tel:', html, re.IGNORECASE))


def _no_external_requests(html: str) -> bool:
    urls = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)["\']', html, re.IGNORECASE)
    return all(_ALLOWED_EXTERNAL_HOSTS.match(u) for u in urls)


def audit_html(html: str) -> dict[str, bool]:
    """Run the full checklist against `html`. Pure, deterministic."""
    html = html or ""
    return {
        "title": _has_title(html),
        "meta_description": _has_meta(html, "description"),
        "viewport": _has_meta(html, "viewport"),
        "single_h1": _single_h1(html),
        "og_title": _has_meta(html, "og:title"),
        "og_description": _has_meta(html, "og:description"),
        "og_image": _has_meta(html, "og:image"),
        "jsonld_local_business": _has_jsonld_local_business(html),
        "img_alt": _all_img_have_alt(html),
        "tel_link": _has_tel_link(html),
        "no_external_requests": _no_external_requests(html),
    }


def seo_pass(results: dict[str, bool]) -> bool:
    """True only if every check passed."""
    return all(results.values())


def failed_checks(results: dict[str, bool]) -> list[str]:
    return [name for name, ok in results.items() if not ok]


def audit_site_dir(site_dir: str) -> dict[str, bool]:
    """Read site_dir/index.html and run the audit. Raises FileNotFoundError
    if index.html is missing (there is nothing to publish)."""
    index = os.path.join(site_dir, "index.html")
    if not os.path.isfile(index):
        raise FileNotFoundError(f"no index.html in {site_dir}")
    with open(index, "r", encoding="utf-8") as f:
        html = f.read()
    return audit_html(html)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leadengine.seo", description=__doc__)
    p.add_argument("dedupe_key")
    p.add_argument("--db", default=_DEFAULT_DB)
    args = p.parse_args(argv)

    from .crm import init_pipeline, pipeline_row
    from .store import init_db

    conn = init_db(args.db)
    init_pipeline(conn)
    row = pipeline_row(conn, args.dedupe_key)
    conn.close()
    if not row or not row.get("site_dir"):
        print(f"[seo] no site_dir for {args.dedupe_key!r}", file=sys.stderr)
        return 2

    try:
        results = audit_site_dir(row["site_dir"])
    except FileNotFoundError as e:
        print(f"[seo] {e}", file=sys.stderr)
        return 2

    for name in _CHECK_NAMES:
        status = "PASS" if results[name] else "FAIL"
        print(f"{status:<5} {name}")

    overall = seo_pass(results)
    print(f"\n{'PASS' if overall else 'FAIL'} overall")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
