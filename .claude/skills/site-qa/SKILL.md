---
name: site-qa
description: QA-review a generated business site on desktop and mobile via screenshots; verdict PASS/FAIL with concrete fixes. Use after sitegen builds a site (stage=built).
---

# site-qa — independent review of a generated site

Input: `dedupe_key` + site dir `projects/agency/sites/<slug>/`. Run this in a FRESH agent that did not build the site (writer ≠ reviewer).

## Steps

1. Screenshot both viewports (absolute file:// path required):
   ```bash
   agent-browser set viewport 1366 768
   agent-browser open "file:///C:/Users/Win/projects/agency/sites/<slug>/index.html"
   agent-browser wait 1500
   agent-browser screenshot projects/agency/sites/<slug>/qa_desktop.png
   agent-browser set viewport 390 844
   agent-browser reload
   agent-browser wait 1500
   agent-browser screenshot projects/agency/sites/<slug>/qa_mobile.png
   ```
2. Read BOTH screenshots (Read tool — actual pixels, not assumptions).
3. Read the site's `index.html` source.

## Checklist (all must hold for PASS)

- Photos load (no broken-image icons); hero photo looks intentional, not stretched/squashed.
- No horizontal scroll or overflow at 390px; text readable on mobile.
- Phone number visible above the fold and is a working `tel:` link in source.
- No emoji, no lorem ipsum, no invented facts (cross-check copy against `enriched_json`).
- Palette coherent (not default-blue-on-white template look); contrast readable.
- Hours/address/contact present if the data had them.

## Verdict

Write the report:
```bash
python -c "import sys, json; sys.path.insert(0, 'projects/agency'); from leadengine import store, crm; c = store.init_db('projects/agency/leads.db'); crm.init_pipeline(c); crm.set_qa(c, sys.argv[1], json.loads(sys.argv[2]), sys.argv[3] == 'PASS')" <dedupe_key> "{\"verdict\": \"PASS\", \"notes\": [...]}" PASS
```

- PASS → stage becomes `qa_passed`; report verdict upstream.
- FAIL → stage stays `built`; return the concrete fix list. Orchestrator sends fixes back to a sitegen agent (max 2 rebuild rounds, then flag for human).
