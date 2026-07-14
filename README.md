# open-agency — free, local, open-source AI website agency

The free alternative to $400 "autonomous website agency" tools. Runs on your
machine, on the Claude (or other agent) plan you already pay for. No SaaS, no
telemetry, no license key.

Full pipeline: find local businesses with **no website** → enrich (photos, hours,
reviews) → build a bespoke single-file site → independent AI QA (desktop+mobile
screenshots) → deploy → personalized email pitch → 5-touch follow-up sequence —
all tracked in a tiny local SQLite CRM. Pure Python stdlib + a browser CLI;
no API keys, no third-party Python deps.

## How it works

| Stage | What happens | Module |
|---|---|---|
| 1. Source | Scrape Google Maps for a niche+region, keep only businesses **without** a website, score by purchase likelihood, dedupe into CRM | `leadengine/cli.py` |
| 2. Enrich | Pull real photos, hours, reviews, description from public pages | `leadengine/enrich.py` |
| 3. Build | Agent builds a bespoke single-file site from real photos — no templates | `.claude/skills/sitegen` |
| 4. QA | A **fresh** agent (never the builder) screenshots desktop+mobile and passes/fails against a checklist | `.claude/skills/site-qa` |
| 5. Deploy | Local preview or GitHub Pages; publishing requires explicit `--yes` | `leadengine/deploy.py` |
| 6. Pitch | Personalized email referencing real business details, sent from **your** SMTP | `leadengine/outreach.py` |
| 7. Follow-up | 5-touch sequence (days 2/5/9/14), stops on reply | `leadengine/outreach.py` |

Stage machine (`leadengine/crm.py`): `new → enriched → built → qa_passed →
deployed → pitched → follow_up → replied → won` (any stage → `dead`). Re-running
a query never duplicates leads or resets CRM state.

## Setup (once)

Requires Python 3.10+ and the [`agent-browser`](https://github.com/vercel-labs/agent-browser) CLI.

```bash
python -m leadengine.wizard   # SMTP creds -> .env, region/provider -> config.json
```

`.env` is gitignored. Set `DRY_RUN=1` in it to rehearse outreach without sending
a single real email.

## Run

With Claude Code: open this folder and run `/agency-run 3` — the orchestrator
(`.claude/commands/agency-run.md`) drives the whole loop for 3 leads.

Or drive each stage by hand from the repo root:

```bash
python -m leadengine.cli "plumbers in austin tx" --limit 20      # 1. source leads
python -m leadengine.enrich <dedupe_key>                          # 2. photos/hours/reviews
# 3-4. build + QA: agent skills `sitegen` and `site-qa` (separate agents, writer != reviewer)
python -m leadengine.deploy <dedupe_key> --provider local         # 5. local | gh-pages (--yes to publish)
python -m leadengine.outreach pitch <key> --to a@b.c --subject "..." --body-file p.txt   # 6. touch 1
python -m leadengine.outreach due                                 # 7. list follow-ups due
python -m leadengine.outreach touch <key> 2 --subject "..." --body-file f.txt
```

## Preference learning

Site style rules you teach it accumulate in `prefs.md` — every piece of
feedback becomes a standing rule the builder reads before every future build.

## Tests

```bash
python -m unittest discover -v
```

## Why this instead of the $400 tool

- **Free and open.** Read every line. Modify anything. No license, no lock-in.
- **100% local.** Leads, CRM, sites, sent-mail log — files on your disk. No
  vendor account, no telemetry.
- **Writer ≠ reviewer QA.** The agent that builds a site never passes its own
  work; an independent agent verdicts against screenshots. Closed tools have
  no enforceable proof-gate.
- **Safety gates.** Publishing and emailing require explicit approval; DRY_RUN
  rehearsal; nothing is ever sent without SMTP creds *you* typed in.
- **Small and readable.** Every stage is one stdlib-only module with tests.

## Ethics / anti-spam

This tool sends real email to real businesses. Use your own identity, honor
opt-outs immediately, follow CAN-SPAM/GDPR/your local law, and keep volumes
human-scale. The 5-touch sequence ends with a polite close-the-loop, not
infinite nagging. Don't be the reason cold email gets worse.

## License

MIT
