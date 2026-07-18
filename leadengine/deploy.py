"""Deploy a generated static site dir to free hosting.

    python -m leadengine.deploy <dedupe_key> [--provider local|gh-pages] [--yes] [--db PATH]

Providers:
  local     - no-op, returns file:// URL of index.html. Default, always available.
  gh-pages  - requires `gh` CLI (authed). Pushes site dir to a new/existing
              GitHub repo and enables Pages.
  vercel/netlify - not installed on this machine; stubbed, raise NotImplementedError.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

from .seo import audit_site_dir, failed_checks, seo_pass

_PROVIDERS = ("local", "gh-pages", "vercel", "netlify")
_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "leads.db")


def detect_providers() -> dict[str, bool]:
    """Which deploy CLIs are installed on PATH."""
    return {
        "gh": shutil.which("gh") is not None,
        "vercel": shutil.which("vercel") is not None,
        "netlify": shutil.which("netlify") is not None,
        "wrangler": shutil.which("wrangler") is not None,
    }


def _run(args: list[str], cwd: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a subprocess, capture output. Never raises on non-zero exit."""
    try:
        return subprocess.run(
            args, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise RuntimeError(f"gh/git command failed: {e}") from e


def _deploy_local(site_dir: str) -> str:
    index = os.path.abspath(os.path.join(site_dir, "index.html"))
    if not os.path.isfile(index):
        raise FileNotFoundError(f"no index.html in {site_dir}")
    return "file:///" + index.replace(os.sep, "/")


def _gh_login() -> str:
    r = _run(["gh", "api", "user", "-q", ".login"])
    if r.returncode != 0:
        raise RuntimeError(f"gh api user failed: {r.stderr.strip()}")
    login = r.stdout.strip()
    if not login:
        raise RuntimeError("gh api user returned empty login")
    return login


def _gh_ensure_repo(repo: str) -> None:
    r = _run(["gh", "repo", "create", repo, "--public",
              "--description", "Generated site (leadengine deploy)"])
    if r.returncode != 0 and "already exists" not in (r.stderr + r.stdout).lower():
        raise RuntimeError(f"gh repo create failed: {r.stderr.strip()}")


def _gh_push_site(site_dir: str, repo: str) -> None:
    if not os.path.isdir(os.path.join(site_dir, ".git")):
        r = _run(["git", "init", "-b", "main"], cwd=site_dir)
        if r.returncode != 0:
            raise RuntimeError(f"git init failed: {r.stderr.strip()}")

    r = _run(["git", "add", "-A"], cwd=site_dir)
    if r.returncode != 0:
        raise RuntimeError(f"git add failed: {r.stderr.strip()}")

    r = _run(["git", "commit", "-m", "deploy"], cwd=site_dir)
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr).lower():
        raise RuntimeError(f"git commit failed: {r.stderr.strip()}")

    remote_url = f"https://github.com/{repo}.git"
    r = _run(["git", "remote", "add", "origin", remote_url], cwd=site_dir)
    if r.returncode != 0:
        r = _run(["git", "remote", "set-url", "origin", remote_url], cwd=site_dir)
        if r.returncode != 0:
            raise RuntimeError(f"git remote set-url failed: {r.stderr.strip()}")

    r = _run(["git", "push", "-f", "origin", "main"], cwd=site_dir)
    if r.returncode != 0:
        raise RuntimeError(f"git push failed: {r.stderr.strip()}")


def _gh_enable_pages(repo: str) -> None:
    r = _run(["gh", "api", "-X", "POST", f"repos/{repo}/pages",
              "-f", "source[branch]=main", "-f", "source[path]=/"])
    if r.returncode == 0:
        return
    out = (r.stdout + r.stderr).lower()
    if "already" in out or "409" in out:
        return
    r2 = _run(["gh", "api", "-X", "PUT", f"repos/{repo}/pages",
               "-f", "source[branch]=main", "-f", "source[path]=/"])
    if r2.returncode != 0:
        raise RuntimeError(f"gh api pages enable failed: {r.stderr.strip()} / {r2.stderr.strip()}")


def _deploy_gh_pages(site_dir: str, slug: str, force: bool = False) -> str:
    if not detect_providers()["gh"]:
        raise RuntimeError("gh-pages provider requires the `gh` CLI (not installed)")
    if not force:
        results = audit_site_dir(site_dir)
        if not seo_pass(results):
            raise RuntimeError(
                "SEO audit failed, refusing to publish "
                f"(failed: {', '.join(failed_checks(results))}); use --force to override"
            )
    owner = _gh_login()
    repo = f"{owner}/{slug}-site"
    _gh_ensure_repo(repo)
    _gh_push_site(site_dir, repo)
    _gh_enable_pages(repo)
    return f"https://{owner}.github.io/{slug}-site/"


def deploy_site(
    site_dir: str, slug: str, provider: str = "local", yes: bool = False, force: bool = False
) -> str:
    """Deploy site_dir under the given provider. Returns the published URL.

    Any non-local provider is an outward-facing publish action and requires
    yes=True (mirrors --yes on the CLI). gh-pages additionally requires a
    passing SEO audit (leadengine.seo) unless force=True.
    """
    if provider not in _PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose from {_PROVIDERS}")

    if provider != "local" and not yes:
        raise RuntimeError("publishing requires --yes")

    if provider == "local":
        return _deploy_local(site_dir)
    if provider == "gh-pages":
        return _deploy_gh_pages(site_dir, slug, force=force)
    # vercel / netlify: CLI not installed on this machine
    raise NotImplementedError(f"{provider}: CLI not installed")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="leadengine.deploy", description=__doc__)
    p.add_argument("dedupe_key", help="pipeline row key to deploy")
    p.add_argument("--provider", choices=_PROVIDERS, default="local")
    p.add_argument("--yes", action="store_true", help="confirm publishing (required for non-local)")
    p.add_argument("--force", action="store_true", help="skip the SEO audit gate on gh-pages publish")
    p.add_argument("--db", default=_DEFAULT_DB, help="SQLite pipeline path")
    args = p.parse_args(argv)

    from .crm import pipeline_row, set_stage, set_site, init_pipeline  # noqa: F401
    from .store import init_db

    conn = init_db(args.db)
    init_pipeline(conn)
    row = pipeline_row(conn, args.dedupe_key)
    if not row or not row.get("site_dir"):
        print(f"[deploy] no site_dir for {args.dedupe_key!r}", file=sys.stderr)
        conn.close()
        return 2

    slug = os.path.basename(os.path.normpath(row["site_dir"]))
    try:
        url = deploy_site(row["site_dir"], slug, provider=args.provider, yes=args.yes, force=args.force)
    except (RuntimeError, NotImplementedError, FileNotFoundError, ValueError) as e:
        print(f"[deploy] failed: {e}", file=sys.stderr)
        conn.close()
        return 1

    set_site(conn, args.dedupe_key, row["site_dir"], site_url=url)
    set_stage(conn, args.dedupe_key, "deployed")
    conn.close()
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
