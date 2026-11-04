# Design Reference Atlas

Researcher run: 2026-11-03, 21:46 to 21:56 EST (hard stop; about 10 minutes of research time in total).
Method: curl (HTTP status, raw HTML, text extracted with a tag-stripping script) only. No browser, no sign-up, no purchase.
Labels: VERIFIED = fetched and read in this run. INFERRED = reasoned from what was fetched, not confirmed.

Honest scope: the brief asked for 30 or more references. The true count is **22 references** (A1-A6, B1-B3,
C1-C5, D1-D4, E1-E4; several group a family of named items), all from pages actually fetched, plus **3 access notes**
(A7: tools URLs seen in HTML but not fetched; F1-F2: Collect UI pages fetched but no design readable). Two GetLayers
item URLs were tried (`/templates/creative-director`, `/templates/clarix`) and both returned 404; no other template,
screen, flow or design detail page was opened on any platform;
references below are the catalogue entries, taxonomies and component pages that the fetched pages expose.
Motion cannot be observed with curl, so every "motion" field says what the page claims or says "not observable
without a browser". No source code or prompt was retrieved from GetLayers.

## 1. Per-platform access table

| Platform | Reachable? (VERIFIED) | What an unauthenticated visitor can see (VERIFIED) | BLOCKED parts and why |
|---|---|---|---|
| GetLayers (getlayers.ai) | Yes. `/` 200 (807 KB), `/pricing` 200, `/terms-of-use` 200, `/terms` 404 | Catalogue of named templates, 3D scenes, gradients, sections and 13 "tools" pages; pricing; full terms of use | Premium prompts need a paid plan (Unlimited $139 lifetime, Unlimited Plus $199 lifetime). Source code and the MCP only in the Full Stack plan. Backgrounds/gradients/Figma only from Unlimited Plus. Fair use 10 or 20 prompt copies per type per day. Which items are free was not determined: two guessed item URLs returned 404 "Layer not found", and the `templates/<slug>` strings in the HTML are storage assets (webp/mp4 previews), not page routes |
| Mobbin (mobbin.com) | Yes. `/` 200 (1.06 MB) | Marketing page: "over 600,000" screens; library split into Apps, Sites, Screens, Flows, Animations, UI Elements; MCP for AI agents; Finance+ add-on | The library itself (`/explore`) is behind "Join for free"/"Log in" (INFERRED from the page's calls to action; `/explore` not fetched). MCP is "Available on Pro & Team plans"; Finance+ (60+ finance apps incl. flows behind KYC walls) on Team & Enterprise |
| SaaSFrame (saasframe.io, redirects to www) | Yes. `/` 200 (382 KB) | Full taxonomy with counts: 41 page categories, 47 section patterns, product-screen categories (249 category/pattern links in the HTML) | Individual examples not opened. Paywall status of examples not determined |
| Page Flows (pageflows.com) | Yes. `/` 200 (240 KB) | Taxonomy: iOS / Android / Web / Email; popular products; popular screens; UI elements; flows; account-management sub-flows | Flow recordings not opened; whether recordings play for logged-out visitors not determined |
| Component Gallery (component.gallery) | Yes. `/` 200, `/components/tabs/` 200, `/components/accordion/` 200 | Fully open: 60 components, 95 design systems, 2,671 examples; each component page has examples, description, markup, styling, interactivity, usage guidelines, footnotes, resources | Nothing blocked. It is a free reference that links out to each design system |
| Collect UI (collectui.com) | Yes. `/` 200 (30 KB); `/challenges/card` redirects to `/designs/card-ui-design-inspiration` 200 (30 KB) | Shell of a daily-inspiration gallery inside the "Panda Network"; categories, designers, trending; sponsor slots | The grid of designs is not in the static HTML (both pages about 30 KB with a "Loading..." placeholder), so no individual design could be read without a browser. Not a login wall, a client-rendering limit |

## 2. References

Fields: 1 name + URL (status) · 2 demonstrates · 3 relevance · 4 motion · 5 technique · 6 accessibility ·
7 performance · 8 prompt/source access · 9 licence · 10 original adaptation.

### A. GetLayers

Licence for every GetLayers item (VERIFIED, `/terms-of-use` section 08): content, free and premium, may be used
"to generate content for personal or commercial projects; to create websites, designs, or other deliverables for
yourself or your clients; and as inspiration or starting points for your own work. Every layer, including free
layers, is licensed for commercial use." Prohibited: to "scrape, copy, or redistribute the prompt library itself
(in whole or in part) for resale or as a competing product." Operator: a company in Warsaw, Poland.
Prompt/source for every item below: **NOT retrieved**. Premium prompts require a plan; source code requires the
Full Stack plan (pricing page, VERIFIED). Item pages could not be opened by URL: `/templates/creative-director` and
`/templates/clarix` both returned **404 "Layer not found"** (VERIFIED, 21:49). The `templates/<slug>` strings in the home
HTML are storage assets, not routes: `https://storage.getlayers.ai/templates/clarix.webp`, `clarix.mp4`,
`clarix-preview.mp4`, plus `-desktop` / `-mobile` variants (VERIFIED in HTML). So the catalogue's motion previews are
pre-rendered video loops with a WebP poster, the same technique as the owner's `loop.mp4` / `loop.webm` tiles
(INFERRED that they autoplay on hover; not observable). Real item routes are produced client-side and were not found.

**A1. "Creative Director" (Portfolio template).** 1: listed on https://www.getlayers.ai/ (200). 2: a cinematic
single-person portfolio template, the only "Portfolio" tag on the home rail. 3: the closest category to the owner's
site. 4: not observable without a browser. 5: delivered as a prompt to paste into an AI builder (site claim). 6/7:
unknown; prompt-generated sites inherit whatever the AI writes, so contrast, focus order and bundle size must be
checked after generation. 8: not retrieved. 9: commercial use allowed. 10: do not take the template; take the idea
that a portfolio can be "one scene per project" and keep the owner's existing register instrument as the only 3D object.

**A2. "Stride" (Fintech template).** 1: listed on `/` (200). 2: fintech landing direction. 3: the owner's
trading-bot and finance projects. 4-7: not observable / unknown. 8: not retrieved. 9: commercial. 10: borrow the
genre's habit of one oversized figure per screen; on the owner's site that figure must be a real number from a case study
(e.g. the on-time arrivals rate), never a decorative KPI.

**A3. "Clarix", "Nexus", "Prisma", "AI Studio" (AI / Tech templates).** 1: listed on `/` (200). 2: the AI/tech
genre is the largest group on the rail (4 of 13 shown). 3: the owner's ML/RAG projects. 4-7: unknown. 8: not retrieved.
9: commercial. 10 (INFERRED): the AI genre is crowded with glowing orbs; the owner's differentiator should be showing
the model's limits (backtest MAPE, refusals) as designed objects, which the current case pages already do.

**A4. 3D scene prompts: "Orb" and "Glass Halo" (Fluid & Iridescent), "Pixel Glass", "Halcyon Gate", "Rift Stone"
(3D Element), "Aurum Peak", "Argent Massif" (Waves & Terrain).** 1: listed on `/` (200). 2: one hero 3D object or
terrain per page. 3: matches the owner's one-object rule (feedback: "one 3D object, huge type"). 4: not observable.
5 (INFERRED from "3D WebGL scenes" in the meta description): WebGL, likely Three.js. 6: canvas content needs a text
equivalent and a reduced-motion path. 7: a second WebGL context next to the instrument would cost GPU and memory;
one context per page. 8: not retrieved. 9: commercial. 10: "Waves & Terrain" maps well to data: a terrain built
from a real series (monthly delays, forecast fan) instead of noise.

**A5. Gradient prompts: "Laminar", "Quicksilver", "Komorebi", "Strigil", "Pharos", "Serigraph".** 1: listed on `/`
(200), "Interactive gradient prompts". 2: animated shader gradients as section grounds. 3: section grounds on the
ivory/green palette. 4: claims "interactive"; not observable. 5 (INFERRED): fragment shaders. 6: animated
backgrounds behind text lower legibility; pause control and reduced motion needed. 7: full-screen shaders run every
frame; cap pixel ratio and stop when off-screen. 8: gradients are Unlimited Plus only (pricing, VERIFIED). 9:
commercial. 10: a static, near-still gradient that shifts only when the chapter changes (one transition per chapter,
not a looping animation), which keeps the instrument the only moving thing.

**A6. Section prompts: "Roadmap Ascent" (Process / Roadmap), "Cards Almanac" and "Cards Cascade" (Cards),
"Mirror Hall" and "Spotlight" (Carousel), "Colonnade" (Features), "Equator" (Showcase).** 1: listed on `/` (200).
2: reusable interactive sections. 3: "Roadmap Ascent" fits a process/timeline of the owner's work; "Almanac" fits an
index of projects. 4: not observable. 6: carousels need pause, keyboard and visible position. 7: unknown. 8: not
retrieved. 9: commercial. 10: an "almanac" archive where each project is a dated entry by year, extending the existing
`all.html` editorial index instead of adding cards (the owner rejected a thumbnail wall).

**A7. GetLayers tools pages: `/tools/text-animations`, `/tools/custom-cursors`, `/tools/shader-backgrounds`,
`/tools/dither-art`, `/tools/ascii-studio`, `/tools/particle-forms`, `/tools/refract`, `/tools/liquid-colour`,
`/tools/orb-studio`, `/tools/holographic-cloth`, `/tools/image-motion`, `/tools/svg-to-3d`, `/tools/image-compressor`.**
1: links VERIFIED in the home HTML; the pages themselves were not fetched. 2: generators for each effect family.
3: text animation and cursor are the two the brief named. 4-7: not observed. 8: not retrieved. 9: commercial per terms.
10: a custom cursor only on fine pointers and only inside the instrument chapter (it already has pointer drag), never
site-wide; text animation limited to the chapter titles, with the static text in the HTML for no-JS and reduced motion.

### B. Mobbin

**B1. Mobbin library structure.** 1: https://mobbin.com/ (200). 2: one library split six ways (Apps, Sites,
Screens, Flows, Animations, UI Elements), and a natural-language search demo ("Show me how top apps design paywalls
..." then "Found 5 apps"). 3: the owner's archive has the same problem (many projects, several ways in: by kind, by
tool, by year). 4: not observable. 5: page is about 1 MB of HTML (heavy server-rendered marketing page). 6: unknown.
7: 1 MB HTML on the marketing page alone. 8: library gated (see table). 9: Mobbin screenshots are of third-party
apps; nothing was copied. 10: offer the archive the same "lenses" idea with the owner's real facets (kind, tool, year,
status), as tabs over one list, plus a plain-language query bar (the archive's query bar already has clauses).

**B2. Mobbin "Finance+" and MCP offers.** 1: https://mobbin.com/ (200). 2: vertical depth (60+ investment, banking
and crypto apps, flows behind KYC walls) and agent access via MCP. 3: shows how a library sells depth in one vertical.
4-7: n/a. 8: Team & Enterprise / Pro & Team plans. 9: paid. 10: a "deep" vertical on the portfolio: the four flagship
chapters as the depth tier, the archive as the breadth tier, said in one line on the home.

**B3. Mobbin customer stories (Cursor, Sanctum, OKX).** 1: https://mobbin.com/ (200). 2: proof via named teams and
one quote with name and role. 3: trust structure for the contact/about area. 6/7: n/a. 9: n/a. 10: the owner has no
clients to quote; the equivalent is named, checkable evidence (repository links, test counts, dates) next to each claim.

### C. SaaSFrame

**C1. SaaSFrame page taxonomy (41 page types with counts).** 1: https://www.saasframe.io/ (200). 2: counts show what
SaaS sites actually build: Landing Page 296, Pricing Page 211, About Page 130, Blog Feed 97, Careers 96, Features 81,
Customer Stories 73, Integrations Library 67, Comparison 55, 404 Page 45, Contact 39. 3: a portfolio needs only a few:
landing (home), customer stories (case studies), about, contact, 404. 4: n/a. 9: screenshots of third-party sites.
10: build the 404 deliberately (45 examples suggest it is a real design surface): the instrument "missing a part",
with links to the archive.

**C2. SaaSFrame section patterns: "Statistics" (52) and "Case Study" (10).** 1: https://www.saasframe.io/ (200),
`/patterns/...`. 2: statistic bands and case-study blocks as trust structure. 3: the owner's figures. 6: statistics
must be text, not images. 10: a statistics band where every number links to the case-study paragraph that sources it.

**C3. SaaSFrame "Bento Grid" (55) and "Tabs" (29) sections.** 1: same page (200). 2: bento grids are now a very common
pattern. 3: risk of looking templated. 10: avoid bento on the home (generic); use tabs only where content is truly
parallel (the system chapter's arrangements).

**C4. SaaSFrame "Timeline" (16), "Awards & Recognition" (18), "Customer Logos" (43), "Testimonial" (88).** 1: same
page (200). 2: trust sections. 3: the owner's equivalent is a dated timeline of projects and tools, not logos. 10: a
timeline drawn from `project.json` dates, rendered as text first.

**C5. SaaSFrame product-screen categories: "Empty State" (115), "Dashboard" (191), "Analytics" (81), "Details" (83),
"Import & Export" (40).** 1: same page (200). 2: application states as a design surface. 3: the owner's analytics
dashboards. 10: show each dashboard project's empty, loading and error states in its case study, which most portfolios skip.

### D. Page Flows

**D1. Page Flows platform split and taxonomy.** 1: https://pageflows.com/ (200). 2: content organised four ways:
platform (iOS, Android, Web, Email), product, screen type, flow. 3: the exploration-to-detail journey the brief asked
for. 4: flows are recordings (INFERRED from "user flows"); not observable. 10: case studies that read as a flow:
problem, then each step of the work in order, with "where you are" visible (the case pages already have section chips).

**D2. Page Flows "Popular Screens": Sign Up, Login, Checkout, Upgrade, Filter, Product details, Search, Dashboard,
Plans & pricing, Forgot password.** 1: same page (200). 2: the screen types people look up most. 3: "Search",
"Filter" and "Product details" match the archive and its dialog. 10: treat the archive dialog as the "product details"
screen: one fact sheet, with keyboard close and a stable URL (already `#<slug>`).

**D3. Page Flows "Popular Flows" and account flows: Onboarding, Booking, Buying, Adding, Chat; Upgrading,
Deactivating & Deleting, Logging In/Out, Editing Profile, Resetting Password, Verifying.** 1: same page (200).
2: flows as named, repeatable journeys. 3: the contact journey (the only "conversion" on the site). 10: a contact flow
of at most two steps: copy e-mail (already present) or open a pre-filled mail, with a visible confirmation.

**D4. Page Flows popular products: Revolut, Robinhood, Monzo, N26, Chase, Stripe, Notion, Slack, Asana, Dovetail,
Amplitude** ("Robinhood" and "Amplitude" expanded from the truncated labels "Robinh..." and "Ampli..." in the page). 1: same page (200). 2: fintech and analytics products dominate. 3: these are the products the owner's
target employers build. 9: recordings of third-party apps; nothing copied. 10: study how Amplitude/Dovetail present a
chart's state change (INFERRED as useful; not viewed).

### E. Component Gallery

**E1. The Component Gallery home.** 1: https://component.gallery/ (200). 2: 60 components, 95 design systems, 2,671
examples; ⌘K search; System/Light/Dark theme switch. 5: built with Astro (VERIFIED: `data-astro-cid` attributes) and
Tailwind classes. 6: theme switch offers "System" first, a good default. 7: home 100 KB HTML. 9: free reference; each
example links to its own design system. 10: add a "System" option if the site ever gets a theme switch; the ⌘K pattern
fits the archive's query bar (focus it with "/" and ⌘K).

**E2. Tabs**, https://component.gallery/components/tabs/ (200). 2: 80 examples; filters by tech (React 48, Web
Components 21, ...) and by features: Code examples 68, Open source 59, Usage guidelines 44, **Accessibility 22**,
**Accessibility issues 4**; page sections Description, Markup, Styling, Interactivity, Usage guidelines. 3: the archive's
kind tabs. 6: only 22 of 80 systems document tab accessibility. 10: implement the archive tabs to the WAI-ARIA tabs
pattern (arrow keys between tabs, one tab stop) and say so in `docs/`.

**E3. Accordion**, https://component.gallery/components/accordion/ (200). 2: "a vertical stack of interactive
headings used to toggle the display of further information." 3: case-study sections on mobile. 6: native
`<details>/<summary>` gives keyboard and screen-reader support for free. 10: use `<details>` for long case-study
appendices on mobile only, open by default on desktop.

**E4. Carousel, Tree view, Popover** (descriptions on the home, 200). 2: popover "differs from a tooltip in that it is
usually triggered via click instead of hover and can contain interactive elements." 3: the instrument's marks and
glossary terms. 6: hover-only tooltips fail on touch and keyboard. 10: definitions (e.g. MAPE) as click popovers with
the native `popover` attribute; tree view for a project's repository structure in a case study.

### F. Collect UI

**F1. Collect UI home**, https://collectui.com/ (200, 30 KB). 2: daily curated UI shots, Designers, Categories,
Trending; part of the "Panda Network" (Best Designs On X, Curations Supply, Flat UI Colors). 3: breadth of visual
inspiration. 5: designs load client-side ("Loading..." in static HTML). 7: sponsor slots and network launcher on the
page. 8/9: shots belong to their designers. 10: none taken; no design was readable.

**F2. Collect UI "card" category**, `/challenges/card` redirects to
https://collectui.com/designs/card-ui-design-inspiration (200). 2: card UI inspiration (title and meta only;
grid not in static HTML). 10: not adaptable from what was seen. A browser pass is needed for Collect UI.

## 3. Five insights for the owner's portfolio (INFERRED from the above)

1. Every library studied organises one collection through several facets (Mobbin six, Page Flows four, SaaSFrame three
   with counts). The archive should do the same with the owner's real facets and show counts per facet.
2. Trust on SaaS sites comes from statistics, case studies, timelines and logos. The owner has no logos or quotes, so
   each number should link to its source paragraph and repository.
3. Accessibility is documented by a minority of design systems (Component Gallery tabs: 22 of 80). Following the
   WAI-ARIA patterns for tabs, dialog and popover, and saying so, is a cheap differentiator.
4. The cinematic genre (GetLayers) is built from one hero object, a shader ground and animated type. The owner's site
   already has the object; the gap is restraint: no second WebGL context, and grounds that change once per chapter.
5. Empty, error and 404 states are a real design surface (SaaSFrame: 115 empty-state screens, 45 404 pages). Designing
   them sets a portfolio apart from template sites.

## 4. Not done (for the next run)

- No individual GetLayers item page opened, so free versus premium per item and prompt visibility are unknown.
- Mobbin `/explore`, Page Flows recordings, SaaSFrame example pages, Collect UI grid: need a browser or a login.
- No motion was observed anywhere (curl only).

## Owner-supplied sources (2026-11-04)

Method: curl with a browser user agent on 2026-11-03, text extracted from the returned HTML. No browser, no login, no motion actually watched. References below are named from titles and slugs in the served HTML, so each one still needs a visual check before it informs a decision.

### motionsites.ai
- URL and status: https://motionsites.ai/ returns 200. /pricing and /3d return 404 (single page app routes not served to curl).
- Visible without login: hero ("Premium AI Website Prompts"), nav (MCP, Backgrounds, TOP, Academy, 3D, Affiliate), and a card list of prompt titles, for example "NOVA Space Systems Landing Page", "Orbit Engineers Agency", "Digital Epoch Hero Section", "Aetheris Voyage Hero Section", "Glow Features", an "Animated backgrounds" video section. Operated by Viktor Odainyi, sole trader.
- BLOCKED: prompt text itself, the "800+ 3D websites" library, pricing. Whether any prompt is free could not be confirmed from curl.
- Licence (https://motionsites.ai/terms, 200, last updated 2026-09-30): paid subscriptions and one-time purchases (lifetime plans, prompt packs) via Stripe. Paying users "may copy prompt text and source code into your own projects, modify them, build with them, and publish or sell the websites and apps you create". Forbidden: reselling, redistributing or sharing the prompt text or code itself, republishing the library, scraping or bulk access. Video backgrounds are owned by MotionSites. Commercial use of the resulting site is allowed for paying users; nothing here was bought, so no prompt may be used.
- References (titles only, content BLOCKED):
  1. "NOVA Space Systems Landing Page": a space systems landing page; could inform THE ARRAY hero pacing (dish field plus single headline). Adapt as a plain sky plus array silhouette, not their layout.
  2. "Animated backgrounds" section: looping video backdrops behind a hero; for THE SLAB, a looping loud colour field behind the monolith, rendered by us (CSS or shader), never their video files.
  3. "Digital Epoch Hero Section": title suggests a time based hero; REEL could take the idea of a dated, era stamped opening frame.

### studio.motionsites.ai
- URL and status: https://studio.motionsites.ai/ returns 200.
- Visible: marketing shell for an AI site builder ("Describe what you want. AI designs it, makes your images and videos, and hands you the code"), a 2:32 how-it-works video link, "Pricing 49% OFF", design gallery tabs (Featured, Popular, Recent; Apps, Sections). Gallery cards are not in the served HTML.
- BLOCKED: building, gallery items, pricing details (sign-up required). No separate licence page found; motionsites.ai terms presumably apply (not verified).
- References: none usable without logging in.

### land-book.com
- URL and status: https://land-book.com/ returns 403 (Cloudflare "Just a moment... Enable JavaScript and cookies").
- BLOCKED entirely for curl. Needs a real browser. No references.

### recent.design (and godly.website)
- URL and status: https://recent.design/ returns 200. https://godly.website returns 301 to http://recent.design/?ref=godly, so Godly is now Recent; one entry covers both.
- Visible: shell with categories (Web, Interface, Branding, Motion, Illustration, Posters, Print), sections Launch Videos, Websites, OG Images, App Screenshots, App Icons, Resources, Tools, Skills, Jobs. Feed items are client rendered and not in the HTML.
- BLOCKED (for curl): every individual item. An auth dialog bundle exists, so saving is login-gated; browsing is likely open in a browser (not verified).
- References: none named. Next run: open https://recent.design/ in a browser, filter Motion and Launch Videos, look for scroll films on a solid colour field (THE SLAB) and dark instrument UIs (THE ARRAY).

### landdding.com
- URL and status: https://landdding.com/ returns 200 (has a "Get PRO" tier; the free gallery is visible).
- Visible: 2.7k designs, 40 categories (/c/portfolio, /c/movie, /c/technology, /c/ai), daily and weekly feeds, plus a report at https://landdding.com/state-of-landing-pages-2026. PRO contents not inspected.
- References (from the homepage feed, titles only):
  1. "premotio: finished design into polished motion": a motion tool site; check how it shows one product shot moving through states, useful for REEL (a single frame advanced reel by reel on scroll).
  2. "The Raycast Keyboard": a single hardware object as the hero; directly relevant to THE SLAB (one dark object, loud field, data windows set into it) and THE FOUNDRY (one cast object).
  3. https://landdding.com/c/movie category: film title pages, for REEL's typographic title cards. Browse, do not copy.

### fontinlogo.com
- URL and status: https://fontinlogo.com/ returns 200, redirects to https://www.fontinlogo.com/.
- Visible: logo font database, "Famous fonts" list marked "free font". Join for free gates saving and the generator (not tested).
- Licence note: fontinlogo labels these "free font" but does not state licences. The licences below are from Google Fonts, where all of these are SIL OFL 1.1 and can be self hosted. Verify each OFL.txt at download.
  - Anton (Thunderbolts): condensed grotesque, huge headline type. THE SLAB, REEL title cards. OFL.
  - Orbitron (Star Wars, Stranger Things on that site): geometric display. THE ARRAY instrument labels, sparingly. OFL.
  - Cinzel / Cinzel Decorative (Game of Thrones, Harry Potter): inscribed capitals. THE FOUNDRY, as cast lettering on metal. OFL.
  - Black Ops One (Jurassic Park): stencil. THE FOUNDRY plate stamps, GROUND TRUTH survey markers. OFL.
  - Silkscreen and Press Start 2P (Minecraft, Mario): pixel faces. Small counters in THE ARRAY or GROUND TRUTH readouts. OFL.
  - Bungee (Dragon Ball): vertical and signage capable. REEL marquee or booth signage. OFL.
  Not usable from that list for this work: Game Of Squids and similar novelty faces (licence unknown).

### 60fps.design
- URL and status: https://60fps.design/ returns 200; shot pages such as https://60fps.design/shots/runmo-lab-pulse-heart-ecg-interaction return 200.
- Visible: 2140 shots, 499 apps, 83 motion, 32 snippets, 67 storyboards, filter tags. Video playback was not checked; some snippets or storyboards may be paid (not verified).
- Mobile patterns relevant to a phone scroll film (filter pages under https://60fps.design/shots/filter/):
  1. runmo-lab-pulse-heart-ecg-interaction: a live trace drawn as a pulse. THE ARRAY signal trace or THE SLAB data window on a phone, one line drawing across a narrow column.
  2. runmo-drag-to-adjust-distance-wheel-interaction and runmo-distance-wheel-fill-interaction: a thumb scrubbed wheel. A phone alternative to scroll scrubbing for REEL (a film reel you spin) or the dish azimuth in THE ARRAY.
  3. cred-printing-tickets-shuffle-interaction: tickets printed and stacked. REEL ticket stubs as chapter markers, or GROUND TRUTH flight strips.
  4. revolut-single-use-pulse-card-sweep-morph-animation and revolut-card-ready-animation: one card morphing with a light sweep. THE SLAB monolith reveal and THE FOUNDRY pour highlight scaled to a phone card.
  5. platen-typewriter-intro-how-to-interaction and brick-intro-value-prop-text-flip-interaction: type that prints or flips line by line. Phone captions for any direction, short lines instead of long paragraphs.
  6. Filters worth a browser pass: /filter/scrub, /filter/parallax, /filter/gyroscope (tilt to look across GROUND TRUTH terrain), /filter/ticker, /filter/stats, /filter/progress.

### Summary
- Most useful: motionsites.ai terms are explicit. Paid users may build and sell sites from the prompts but may not share or republish the prompt text, so nothing from it may be copied into this repo unless the owner buys a plan.
- fontinlogo.com gives a quick shortlist of OFL display faces (Anton, Cinzel, Black Ops One, Orbitron, Bungee, Silkscreen) that map onto the five directions; licences come from Google Fonts, since fontinlogo does not state them.
- 60fps.design is the richest open source for phone motion: ECG trace, thumb wheels, ticket stacks, card sweeps and printed type all translate into a phone scroll film.
- godly.website now redirects to recent.design; both, plus studio.motionsites.ai, render their galleries client side, so curl saw only the shell. They need a browser pass.
- BLOCKED: land-book.com (Cloudflare 403), motionsites prompt content and pricing (paywall), studio.motionsites.ai builder (sign-up), recent.design items (client rendered), landdding PRO. No motion was watched anywhere.
