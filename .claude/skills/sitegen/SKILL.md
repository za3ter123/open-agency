---
name: sitegen
description: Build a bespoke single-file website for a local business from its enriched CRM data. Use when the agency pipeline needs a site built for a lead (stage=enriched).
---

# sitegen — bespoke site per business

Input: a lead's `dedupe_key`. Data lives in the agency DB pipeline table (`enriched_json`) and `sites/<slug>/assets/` photos.

## Steps

1. Pull the data:
   ```bash
   python -c "import sys, json, sqlite3; sys.path.insert(0, 'projects/agency'); from leadengine import store, crm; c = store.init_db('projects/agency/leads.db'); crm.init_pipeline(c); r = crm.pipeline_row(c, sys.argv[1]); l = [x for x in store.all_leads(c) if x['dedupe_key'] == sys.argv[1]]; print(json.dumps({'lead': l[0] if l else None, 'pipeline': r}))" <dedupe_key>
   ```
2. Read `projects/agency/prefs.md` — accumulated owner preferences. They OVERRIDE defaults below.
3. Look at 2-3 photos in `sites/<slug>/assets/` (Read tool) — pick the strongest as hero; note dominant colors and mood, derive the palette from the actual photos.
4. Write `projects/agency/sites/<slug>/index.html` — ONE file, inline CSS, zero external requests except the local `assets/` photos (relative paths).

## Design rules (defaults; prefs.md wins)

- Bespoke to the business: palette from its photos, copy from its real category/reviews/hours. Never a generic template look.
- Sections: hero (name, category tagline, phone CTA), about (from description/reviews), photo gallery (real photos only), hours, contact (phone `tel:` link, address, map link to `maps_url`).
- Real content only — never invent services, prices, or testimonials. Quote actual review snippets with "— Google review".
- Mobile-first responsive; readable at 390px and 1366px.
- NO emoji anywhere. NO stock/AI imagery. NO lorem ipsum. If a section has no real data, drop the section.
- Fast: no JS frameworks; vanilla JS only if genuinely needed (usually not).
- Footer: small "Website by <signature from projects/agency/config.json>" line.

## After writing

Record it:
```bash
python -c "import sys; sys.path.insert(0, 'projects/agency'); from leadengine import store, crm; c = store.init_db('projects/agency/leads.db'); crm.init_pipeline(c); crm.set_site(c, sys.argv[1], 'projects/agency/sites/' + sys.argv[2]); crm.set_stage(c, sys.argv[1], 'built')" <dedupe_key> <slug>
```

Then hand off to the `site-qa` skill. Builder never QAs its own site — QA runs in a fresh agent.
