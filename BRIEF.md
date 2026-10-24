# Portfolio brief (2026-10-24, third direction: THE INDEX)

Everything before this is history. No printed objects, no desk, no paper, no boarding pass. This file is the spec; the
research behind it is in `~/projects-site-evidence/index-2026-10-24/RESEARCH.md`.

## Positioning
Rishit Raj Mathur, data analyst, Tampa. The claim the site makes in one line: **219 projects on GitHub, every number
checked against its source.** Audience: recruiters, hiring managers and technical reviewers for data and business analyst
roles. First screen must answer, in under ten seconds, what this person has built and that the evidence is real.
Desired actions: open a flagship case study, browse the index, download the résumé, contact.

## The one idea
**The body of work is a dataset, and the site is a live view of it.** Every one of the 219 public repositories is one point
in a WebGL field: real language, real date, real commit count, real size (pulled from the GitHub API into `data/github.json`).
- The loader is a counter 000 → 219; each count adds a point. The counter lands as the hero's headline. The field stays
  behind the nav for the whole page. Loader becomes nav becomes content (the continuum every current Awwwards winner has).
- Scroll changes the state of the field, not just the copy: hero = the 219 arranged by year and language; flagship 1 = the
  points become the 75.5% (755 of 1000 light up); flagship 2 = 31 points pass one by one; flagship 3 = the points draw the
  forecast line and its band; flagship 4 = 20 of 20 lock to their XBRL figures; about = the points stack by tool; index = the
  points become the real list.
- The index is queryable. A ⌘K bar with real `WHERE` clauses over language, year, kind, tool, topic; results reflow with FLIP.
  Two views: four flagships (curated), and the full 219 (dense table: name · kind · language · year · commits · live link).
- Every project page carries everything from its repo: description, topics, languages, commit count, last push, Pages link,
  README-derived summary, plus the existing case study. Five repos without case studies get them.

## Art direction
- Colour: three roles, used totally. Field **ultramarine #2400FF**. Ink **#0B0B14**. Signal **#D4FF3A** (the data points
  and nothing else). White #FFFFFF for type on the field. No gradients, no glow, no glass, no grain, no rounded cards.
- Type: **Bricolage Grotesque** (variable: opsz 12-96, wdth 75-100, wght 200-800) for everything that is words. Display at
  wdth 75, wght 800, opsz 96, 12-22vw. **JetBrains Mono** for everything that is data (counts, queries, labels). Two faces,
  two jobs.
- Layout: hard edges, full-bleed, no containers. One line of copy per screen. Nav: three items (Work, Index, Contact) plus a
  live strip (Tampa time, "219 repos", "last push N days ago"). Footer is the second hero: "Let's talk", the e-mail, the clock.
- Motion: one easing for entrances `cubic-bezier(0.16, 1, 0.3, 1)`, one for travel `cubic-bezier(0.65, 0, 0.35, 1)`;
  100-150 ms feedback, 300-500 ms view, 500-800 ms authored; the field eases with a frame-rate-independent lerp; nothing
  animates layout. Reduced motion: no loader, the field holds a pose, counts shown final.
- Banned (from the PDFs and the audit): eyebrows over every heading, decorative numbering, cards, gradients, glass, grain
  overlays, custom cursor, autoplay sound, em dashes in copy, "leverage/seamless/unlock" copy, stock imagery, 3D objects.

## Gate
Desktop hero, phone hero, one flagship screen, the index, a recording of loader → hero → scroll → index → case study,
Lighthouse mobile with gzip 90+/100/100/100, the 5-second test (what does this person do?), the no-animation test, and the
"could this intro belong to anyone else?" test. Evidence folder: `~/projects-site-evidence/index-2026-10-24/`.
