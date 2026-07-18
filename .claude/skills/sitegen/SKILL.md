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
   `enriched_json` may carry an optional `booking_url` (per-lead online booking link) — read it if present.
2. Read `projects/agency/prefs.md` — accumulated owner preferences. They OVERRIDE defaults below. Read `projects/agency/config.json` for the signature line and any global `booking_url_pattern`.
3. Look at 2-3 photos in `sites/<slug>/assets/` (Read tool) — pick the strongest as hero; note dominant colors and mood, derive the palette from the actual photos.
4. Pick a design system (below), auto-selected by category unless prefs.md or the lead overrides it.
5. Write `projects/agency/sites/<slug>/index.html` — ONE file, inline CSS, zero external requests except the local `assets/` photos (relative paths). No webfonts, no CDNs, no analytics, no tracking pixels.
6. Write `projects/agency/sites/<slug>/CONTENT.md` — owner edit cheat-sheet (see CMS-lite below).

## Design systems (pick one, prefs.md/lead can override)

Each system = font pairing (stacks only, never webfonts), spacing scale, radius/shadow language, palette derivation, section treatment. Palette is always DERIVED from the business's own photos (dominant/accent colors sampled by eye from the hero photo) filtered through the system's tone — never a stock palette.

| System | Auto-pick for category | Type pairing | Radius/shadow | Tone |
|---|---|---|---|---|
| `warm-artisan` | restaurant, cafe, bakery, bar | Georgia/serif display + system-ui body | soft radius (12-20px), warm low-opacity shadow | earthy, appetite-warm, generous photo crops |
| `sharp-professional` | law, finance, consulting, real estate | system-ui/Segoe UI display (tight tracking) + system-ui body | sharp radius (2-6px), crisp 1px hairline borders, no shadow or near-flat | confident, high-contrast, dense information |
| `fresh-minimal` | salon, spa, fitness, wellness, retail | system-ui display (light weight) + system-ui body | pill radius (999px on CTAs, 16px on cards), airy diffused shadow | light, breathing whitespace, pastel-adjacent |
| `bold-local` | plumber, electrician, contractor, auto, home services | system-ui display (heavy weight, uppercase headlines) + system-ui body | blocky radius (4-8px), hard offset shadow (4px 4px 0) | trustworthy-loud, big CTAs, trade-badge feel |
| `classic-trust` | medical, dental, legal-adjacent, insurance, education | Georgia/Times serif display + system-ui body | conservative radius (6-10px), soft subtle shadow | calm, credentialed, low-saturation palette |

Category not listed → default `classic-trust`. Font stacks (copy exactly, substitute only the named face):
- serif display: `Georgia, 'Times New Roman', serif`
- system-ui: `system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif`

Spacing scale (all systems, use CSS custom properties): `--space-1: 8px; --space-2: 16px; --space-3: 24px; --space-4: 40px; --space-5: 64px; --space-6: 96px;`. Sections use `--space-5`/`--space-6` for vertical padding, never less than `--space-4`.

## Craft rules

- **Container**: single `max-width: 1200px; margin-inline: auto; padding-inline: clamp(20px, 5vw, 48px);` wrapper reused on every section — never a different max-width per section.
- **Fluid type**: headline `font-size: clamp(2rem, 5vw + 1rem, 4rem)`, section heading `clamp(1.5rem, 3vw + 1rem, 2.5rem)`, body `clamp(1rem, 0.5vw + 0.9rem, 1.125rem)`. No fixed px font-sizes on headings.
- **Hero**: asymmetric layout — text block + photo do NOT split 50/50; use an uneven ratio (e.g. 55/45 or a photo that bleeds to the viewport edge) on desktop, full-width stack on mobile. Hero photo art-direction: `object-fit: cover; object-position` chosen to keep the subject (storefront/food/face) in frame, never centered-crop that cuts off the point of interest — inspect the actual photo dimensions before picking object-position.
- **Section rhythm**: alternate background tone (base / tinted) between adjacent sections so scroll has visible cadence; never two identically-styled sections back to back.
- **Hover/focus**: every interactive element (links, buttons, photo tiles) gets a hover state (subtle transform or color shift) AND a visible `:focus-visible` outline — never `outline: none` without a replacement.
- **Transitions**: `transition: transform 150ms ease, opacity 150ms ease` scale only — no scroll-jacking, no parallax, no autoplaying carousels, no animation libraries.
- **Viewports**: build and mentally check both 390px (mobile-first base) and 1366px (desktop). No horizontal overflow at either.
- **Sticky mobile CTA**: fixed bottom bar, mobile only (`@media (max-width: 640px)`), single "Call now" button wired to the same `tel:` link as the hero, `position: fixed; bottom: 0`, safe-area padding (`padding-bottom: env(safe-area-inset-bottom)`), high z-index, add `padding-bottom` to `body` so it never covers the footer.
- Bespoke to the business: palette from its photos, copy from its real category/reviews/hours. Never a generic template look.
- Sections: hero (name, category tagline, rating badge, phone CTA), about (from description/reviews), photo gallery (real photos only), hours, booking/contact.
- Real content only — never invent services, prices, or testimonials. Quote actual review snippets with "— Google review".
- NO emoji anywhere. NO stock/AI imagery. NO lorem ipsum. If a section has no real data, drop the section.
- Fast: no JS frameworks; vanilla JS only if genuinely needed (usually not — sticky CTA and stars are pure CSS/HTML).
- Footer: small "Website by <signature from projects/agency/config.json>" line.

## Google rating badge

In the hero, render a rating badge using real `rating` (float) and `reviews` (count) from the lead data:
- Pure HTML/CSS stars — unicode `★`/`☆` repeated 5x, filled count = `round(rating)`, styled with `color`, no icon fonts/SVGs from a CDN.
- Label: `"<rating> · <reviews> Google reviews"`.
- Wrap the whole badge in `<a href="<maps_url>" target="_blank" rel="noopener">` so it links out to the real Google listing.
- Omit the badge entirely if `rating` or `reviews` is missing — never fabricate a number.

## Booking CTA

- If `enriched_json.booking_url` (per-lead) or a `booking_url_pattern`/`booking_url` in `config.json`/`prefs.md` exists, add a "Book now" CTA section (button linking to it, `target="_blank" rel="noopener"`) alongside the phone CTA — booking is secondary to phone unless prefs.md says otherwise.
- If no booking link exists anywhere, phone CTA (`tel:` link) stays the sole primary CTA. Do not invent a booking link or a placeholder "Book Now" button with no destination.

## SEO block (required in every `<head>`)

- `<title>` — `"<Name> — <Category> in <City>"` (City parsed from `address`).
- `<meta name="description">` — one real-data sentence (name, category, city, standout detail from description/reviews). No filler like "welcome to our website".
- `<meta name="viewport" content="width=device-width, initial-scale=1">`.
- Exactly one `<h1>` on the page (the business name in the hero).
- OG tags: `og:title`, `og:description`, `og:image` (relative path to the hero photo in `assets/`), `og:type=website`.
- JSON-LD `LocalBusiness` in a `<script type="application/ld+json">` block: `name`, `telephone`, `address` (as `PostalAddress`, best-effort parse from the address string), `aggregateRating` (`ratingValue`=rating, `reviewCount`=reviews) only if both are present, `openingHoursSpecification` from real hours data if present.
- All `<img>` tags get descriptive real-content `alt` text (e.g. `alt="<Name> storefront"`, never `alt=""` or generic `alt="photo"`).
- Phone number is a real `tel:` link, not just text.
- No external requests anywhere in the document (no `<link>` to fonts/CDNs, no external `<script src>`, no tracking).

A separate `seo.py` audit gate checks this block automatically — build it right the first time so that gate passes.

## CMS-lite (owner-editable content)

- All editable copy (business name, tagline, about text, hours, phone display, review quotes) lives in ONE contiguous block near the top of `<body>`, wrapped section-by-section with `<!-- EDIT: <what this is> -->` comments directly above each editable line/block. No CSS variables for content, no JS templating — plain HTML the owner can hand-edit in a text editor.
- Alongside `index.html`, write `sites/<slug>/CONTENT.md`: a short cheat-sheet listing, for each editable piece (hours, phone, address, photos, price/service mentions if any), the exact line number or `<!-- EDIT: ... -->` marker to find it in `index.html` and what format to use. No JS CMS, no backend, no build step — the owner opens `index.html` in Notepad and edits between the markers.

## After writing

Record it:
```bash
python -c "import sys; sys.path.insert(0, 'projects/agency'); from leadengine import store, crm; c = store.init_db('projects/agency/leads.db'); crm.init_pipeline(c); crm.set_site(c, sys.argv[1], 'projects/agency/sites/' + sys.argv[2]); crm.set_stage(c, sys.argv[1], 'built')" <dedupe_key> <slug>
```

Then hand off to the `site-qa` skill. Builder never QAs its own site — QA runs in a fresh agent.
