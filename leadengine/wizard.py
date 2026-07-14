"""One-time setup wizard: collect SMTP + business config, write .env + config.json.

    python -m leadengine.wizard                      # interactive
    python -m leadengine.wizard --yes                 # accept all defaults
    python -m leadengine.wizard --smtp-host smtp.x --smtp-user a@b.com ...

Re-running loads current .env / config.json values as the shown defaults.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from datetime import datetime, timezone

_ENV_KEYS = [
    ("smtp_host", "SMTP_HOST"),
    ("smtp_port", "SMTP_PORT"),
    ("smtp_user", "SMTP_USER"),
    ("smtp_pass", "SMTP_PASS"),
    ("from_name", "FROM_NAME"),
    ("from_email", "FROM_EMAIL"),
    ("reply_to", "REPLY_TO"),
]

_GITIGNORE_LINES = [".env", "data/", "sites/", "leads.db"]


def parse_env(text: str) -> dict:
    """Parse KEY=VALUE lines into a dict. Ignores blank lines and '#' comments."""
    out: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def render_env(d: dict) -> str:
    """Render a dict as KEY=VALUE lines (insertion order), trailing newline."""
    return "".join(f"{k}={v}\n" for k, v in d.items())


def merge_gitignore(existing_text: str, needed_lines: list[str]) -> str:
    """Append any of needed_lines missing from existing_text. Preserves content."""
    present = set(existing_text.splitlines())
    missing = [line for line in needed_lines if line not in present]
    if not missing:
        return existing_text
    text = existing_text
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(f"{line}\n" for line in missing)
    return text


def _prompt(label: str, default: str, secret: bool = False) -> str:
    suffix = f" [{default}]" if default and not secret else (" [hidden]" if secret and default else "")
    if secret:
        value = getpass.getpass(f"{label}{suffix}: ")
    else:
        value = input(f"{label}{suffix}: ").strip()
    return value or default


def _resolve(field: str, label: str, flag_value, default: str, use_yes: bool, secret: bool = False) -> str:
    if flag_value is not None:
        return flag_value
    if use_yes:
        return default
    return _prompt(label, default, secret=secret)


def _load_env_defaults(env_path: str) -> dict:
    if not os.path.exists(env_path):
        return {}
    with open(env_path, "r", encoding="utf-8") as f:
        parsed = parse_env(f.read())
    return {field: parsed[key] for field, key in _ENV_KEYS if key in parsed}


def _load_config_defaults(config_path: str) -> dict:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="leadengine.wizard", description=__doc__)
    p.add_argument("--smtp-host")
    p.add_argument("--smtp-port")
    p.add_argument("--smtp-user")
    p.add_argument("--smtp-pass")
    p.add_argument("--from-name")
    p.add_argument("--from-email")
    p.add_argument("--reply-to")
    p.add_argument("--region")
    p.add_argument("--provider", choices=["local", "gh-pages"])
    p.add_argument("--sender-signature")
    p.add_argument("--yes", action="store_true", help="accept defaults for anything not passed as a flag")
    return p


def main(argv: list[str] | None = None, base_dir: str | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if base_dir is None:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_path = os.path.join(base_dir, ".env")
    config_path = os.path.join(base_dir, "config.json")
    gitignore_path = os.path.join(base_dir, ".gitignore")

    env_defaults = _load_env_defaults(env_path)
    config_defaults = _load_config_defaults(config_path)

    smtp_host = _resolve("smtp_host", "SMTP host", args.smtp_host, env_defaults.get("smtp_host", ""), args.yes)
    smtp_port = _resolve("smtp_port", "SMTP port", args.smtp_port, env_defaults.get("smtp_port", "587"), args.yes)
    smtp_user = _resolve("smtp_user", "SMTP user", args.smtp_user, env_defaults.get("smtp_user", ""), args.yes)
    smtp_pass = _resolve("smtp_pass", "SMTP password", args.smtp_pass, env_defaults.get("smtp_pass", ""), args.yes, secret=True)
    from_name = _resolve("from_name", "From name", args.from_name, env_defaults.get("from_name", ""), args.yes)
    from_email_default = env_defaults.get("from_email") or smtp_user
    from_email = _resolve("from_email", "From email", args.from_email, from_email_default, args.yes)
    reply_to = _resolve("reply_to", "Reply-to (optional)", args.reply_to, env_defaults.get("reply_to", ""), args.yes)
    region = _resolve("region", "Region/city for lead searches", args.region, config_defaults.get("region", ""), args.yes)
    signature = _resolve("signature", "Sender signature line", args.sender_signature, config_defaults.get("signature", ""), args.yes)
    provider = _resolve("provider", "Deploy provider (local/gh-pages)", args.provider, config_defaults.get("deploy_provider", "local"), args.yes)

    env_values = {
        "SMTP_HOST": smtp_host,
        "SMTP_PORT": smtp_port,
        "SMTP_USER": smtp_user,
        "SMTP_PASS": smtp_pass,
        "FROM_NAME": from_name,
        "FROM_EMAIL": from_email,
        "REPLY_TO": reply_to,
    }
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(render_env(env_values))

    created_at = config_defaults.get("created_at") or datetime.now(timezone.utc).isoformat()
    config = {
        "region": region,
        "deploy_provider": provider,
        "signature": signature,
        "created_at": created_at,
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    existing_gitignore = ""
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            existing_gitignore = f.read()
    new_gitignore = merge_gitignore(existing_gitignore, _GITIGNORE_LINES)
    with open(gitignore_path, "w", encoding="utf-8") as f:
        f.write(new_gitignore)

    print(f"[wizard] wrote {env_path}")
    print(f"[wizard] wrote {config_path}")
    print(f"[wizard] updated {gitignore_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
