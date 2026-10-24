# Portfolio brief (frozen baseline, 2026-10-24)

This is the fixed specification the portfolio home is built against. Change it by editing this file, not by drifting in code.
The home lives in this repo (`index.template.html`, `portfolio.css`, `home.js`, `build.py`); the case studies share it.

## Positioning

Audience: recruiters, hiring managers and technical reviewers for entry-level data and business analyst roles.
Message, in one line: **Rishit turns raw public data into checked, explained results.** Every professional claim comes
from the résumé at `~/portfolio/resume.pdf`; nothing is added to it.
Desired actions, in order: open a flagship case study, read it, download the résumé, make contact.

## The concept: the analyst's desk

Every project ends as something you could hold, printed with the number its case study proves: a boarding pass (75.5% on
time, 635,459 flights), a till receipt (31 of 31 data tests), a ruler (1.81% backtest error), a Form 10-K booklet (20 of 20
figures within 0.5% of XBRL). The desk is the body of work; one object is one project; the number on it is the evidence.

Acceptance criterion for the signature visual: it must express the work (data turned into checked results), stay
recognisable and compelling as a still image, and gain meaning through interaction. The desk meets this because the
objects are real outputs of real projects, the still is a composed photograph of them, and interaction (lift, count, flip,
fly into the case study) reveals what each one is.

## The sequence

| Moment | What happens | Purpose |
|---|---|---|
| First frame | The camera is close on the boarding pass; 75.5% fills the screen. Plain HTML + one image. | A designed frame before any script runs |
| Awakening | The camera lifts off the pass; the other objects and the desk enter | Depth and the sense of one physical place |
| Reveal | The wordmark RISHIT rises letter by letter, the frame marks draw, the nav drops in | Whose desk this is |
| Transformation | The landing frame is the hero itself; scroll now flies the same camera back down | The opening becomes the interface |
| Exploration | Scroll: "Clean. Model. Explain." passes; the pass hands over to its project screen; each object lifts, counts, flips | Give control, reveal each project |
| Entering a project | The clicked object and title fly into the case study, which opens with the object beside its title | Context is preserved |
| Returning | The object flies back onto its card; the page is where it was | The visitor left and came back |
| Contact | Ink field, a business card that leans to the pointer | Resolution |

Opening rules: a visible Skip button from the first frame; any wheel, key or tap ends it; a repeat visit in the session plays
it at 0.45x; none with a hash, under reduced motion, or when returning from a case study; it ends after 6 s even if frames
never arrive; no sound; no loading percentage.

## Art direction

- Palette: off-white `#F7F5F0`, ink `#15193A`, one accent (cobalt `#3B5BFF`, `#2B45D6` as text). Each project screen takes a
  faint tint from its object. The printed objects keep their own colours.
- Type: Archivo (variable width and weight, self-hosted). Wordmark 19.5vw at weight 900, width 112%. Numbers tabular.
- Materials: a pale oak desk, matte paper, soft real shadows from Blender (EEVEE), no outlines, no glass, no glow.
- Layout: one project per screen; a headline, one number, one line, two links. Dense content lives in the case studies.
- Motion: easing `cubic-bezier(0.2, 0.8, 0.2, 1)`; durations 160 to 420 ms for interface, 760 ms for the object flight,
  2.6 s for the opening. Transform and opacity only in the interface; the camera is pre-rendered frames on a canvas.

## Motion score

| Area | Intensity | Experience |
|---|---|---|
| Opening | High, 2.6 s | The pass, then the desk, then the name |
| Hero | Moderate | Scroll flies the camera; the wordmark parts |
| Project screens | Responsive | Lift, count, flip, driven by scroll; pager follows |
| Into a case study | One orchestrated move | Object and title travel |
| Case study reading | Low | Progress bar, section chips, reveals |
| Contact | One gesture | The card leans |

## Budgets (provisional until measured on named devices)

- First view, transferred: the HTML, `portfolio.css`, the Archivo woff2, one still (about 70 KB), `home.js` and Lenis.
  The 48 flight frames (about 70 KB each) load after first paint, from the close end during the opening.
- Lighthouse mobile on the production build: performance 90+, accessibility 95+, LCP 2.5 s or less, CLS 0.1 or less.
- Sustained motion: judged from recordings and frame pacing on a named device, separately from loading.

## Gate before any further section is built

Desktop hero, phone hero, one project section, the eight-frame storyboard and the recorded signature interaction are
presented together and judged on identity, composition, legibility, continuity and relevance to the work. Only after that
approval do the remaining sections extend the same rules. Evidence for the current proof:
`~/projects-site-evidence/proof-2026-10-24/`.

## Status (2026-10-24, the full build)

The gate was passed and the rules were extended across the site: every section is a camera position on the same desk
(`tools/desk/world.py`), the opening prints the pass before the lift, the case studies share the language, and the 404,
link preview, clock and states exist. Evidence: `~/projects-site-evidence/world-2026-10-24/`.

## Known gaps

- Cross-document View Transitions run in Chrome, Edge and Safari 18.2+; Firefox gets an ordinary navigation.
- Tablet (768x1024), landscape phone and a real throttled phone have not been captured; Safari has not been checked.
- Lighthouse's simulated LCP (3.2 s home, 4.2 s case study) disagrees with real Chrome (under 120 ms); treat the real
  number as provisional until a real device confirms it.
- Nothing has been published to the public Pages site; the work is on the private branch.
