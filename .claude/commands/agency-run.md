# /agency-run — full pipeline loop (free Klaudius)

Run the agency pipeline end-to-end for `$ARGUMENTS` leads (default 3). Run all `python -m leadengine.*` commands from `C:\Users\Win\projects\agency` (the package lives there; it is not importable from the repo root).

## Pipeline per lead (stage machine in leadengine/crm.py)

Stages: new → enriched → built → qa_passed → deployed → pitched → follow_up → replied/won/dead.

0. **Setup check** — if `projects/agency/.env` missing, run `python -m leadengine.wizard` first (ask user for SMTP values; never invent credentials).
1. **Source** (if fewer than N leads in stage `new`): `python -m leadengine.cli "<category> in <region from config.json>" --limit 20` — targets no-website businesses, dedupes into CRM.
2. **Enrich**: `python -m leadengine.enrich <dedupe_key>` — pulls photos/hours/reviews/description via agent-browser. Skip lead (stage dead) if enrichment returns no photos AND no description.
3. **Build**: spawn a Sonnet subagent with the `sitegen` skill for this dedupe_key. One agent per site; parallel across leads is fine.
4. **QA**: spawn a FRESH agent with the `site-qa` skill (never the builder). FAIL → send fix list to a new sitegen agent; max 2 rebuild rounds, then mark lead for human review and continue with others.
5. **Deploy**: `python -m leadengine.deploy <dedupe_key> --provider <config.deploy_provider>`. Non-local providers publish externally and need `--yes` — only pass it if the user has approved publishing (config alone is not consent; ask once per session, remember the answer for the batch).
6. **Pitch**: draft a short personalized email (see below), then `python -m leadengine.outreach pitch <dedupe_key> --to <email> --subject "..." --body-file <tmp>`. No known email → find one during enrichment (site-less businesses often list email on Maps/Instagram); none found → stage stays deployed, flag for human.
7. **Replies**: `python -m leadengine.replies` — scan the IMAP inbox and auto-mark leads `replied` (halts their follow-ups). Run BEFORE follow-ups every session.
8. **Follow-ups**: `python -m leadengine.outreach due` lists due touches (days 2/5/9/14 after pitch). For each, draft touch N body, send via `outreach touch`. Replied leads never appear here.

## Pitch drafting rules

- 5-8 sentences max, plain text, no emoji, no hype words ("revolutionary", "game-changer").
- Lead with something specific: their rating, a real review quote, their category+neighborhood.
- The hook: "built you a website already — look: <site_url>". The site IS the pitch.
- One clear ask: reply if you want it (free/cheap to start). Signature from config.json.
- Follow-up touches escalate gently: 2=did-you-see, 3=one new specific benefit, 4=social proof/scarcity of your time, 5=polite close-the-loop ("last note, I'll take the site down otherwise").

## Preference learning

After ANY user feedback on a generated site or email (style, colors, tone, sections), append the rule to `projects/agency/prefs.md`. sitegen reads prefs.md every build — feedback compounds.

## Status

From `projects/agency`: `python -c "import json; from leadengine import store, crm; c = store.init_db('leads.db'); crm.init_pipeline(c); b = crm.board(c); print(json.dumps({k: len(v) for k, v in b.items()}))"` — print the board at start and end of every run.

## Hard rules

- Never send email without real SMTP config the user entered; DRY_RUN=1 in .env for rehearsal.
- Never publish (non-local deploy) or email without explicit user approval this session.
- Every stage change goes through crm.py — no manual SQL.
- Log each lead's outcome at the end: key, stage reached, url, blockers.
