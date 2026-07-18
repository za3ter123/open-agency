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
- **Design system consistency**: one design system (per `sitegen/SKILL.md` table) applied throughout — fonts, radius, shadow language, and spacing don't drift section to section; matches the category's auto-pick or a documented prefs.md/lead override.
- **Rating badge**: if `enriched_json` has `rating`+`reviews`, hero shows a stars badge with the correct numbers (cross-check exact values) linking to `maps_url`; if either is missing, badge is correctly absent (not fabricated).
- **SEO head block**: `<title>` follows "<Name> — <Category> in <City>", real meta description, viewport tag, exactly one `<h1>`, `og:title`/`og:description`/`og:image` present, JSON-LD `LocalBusiness` present with real phone/address (and `aggregateRating` if rating data exists), every `<img>` has descriptive real-content `alt` text, no external requests (view source — no external `<link>`/`<script src>`/CDN).
- **Sticky mobile CTA**: in the 390px screenshot, a fixed "Call now" bar is visible at the bottom, doesn't overlap footer content, and its `tel:` link matches the hero's.
- **CONTENT.md exists**: `sites/<slug>/CONTENT.md` is present and its edit markers correspond to real `<!-- EDIT: ... -->` comments in `index.html`.

## Verdict

Write the report:
```bash
python -c "import sys, json; sys.path.insert(0, 'projects/agency'); from leadengine import store, crm; c = store.init_db('projects/agency/leads.db'); crm.init_pipeline(c); crm.set_qa(c, sys.argv[1], json.loads(sys.argv[2]), sys.argv[3] == 'PASS')" <dedupe_key> "{\"verdict\": \"PASS\", \"notes\": [...]}" PASS
```

- PASS → stage becomes `qa_passed`; report verdict upstream.
- FAIL → stage stays `built`; return the concrete fix list. Orchestrator sends fixes back to a sitegen agent (max 2 rebuild rounds, then flag for human).
