# ATELIER X Motion System (Frontend Architect draft, 2026-11-03)

Every rule here is PROPOSED unless marked VERIFIED (read in the current `projects-site` code or CLAUDE.md tonight). The system is written so an implementer can follow it without the author. Tokens live in `packages/tokens/motion.css` and are the only place durations and easings are defined; no literal `cubic-bezier` or millisecond value appears in app code.

## 1. Easing curves

| Token | cubic-bezier | Use |
|---|---|---|
| `--ease-out` | 0.16, 1, 0.3, 1 | Entrances, reveals, anything arriving (default) |
| `--ease-in` | 0.7, 0, 0.84, 0 | Exits that leave the screen (short only) |
| `--ease-in-out` | 0.83, 0, 0.17, 1 | Position changes between two on-screen states (tabs, sliders, dialog resize) |
| `--ease-settle` | 0.22, 1.2, 0.36, 1 | Mechanical seating (the dial, the core), a 2 to 4 percent overshoot, never on text |
| `--ease-linear` | 0, 0, 1, 1 | Opacity cross-fades under 200 ms, progress bars, scrubbing |
| `--ease-camera` | 0.45, 0, 0.15, 1 | Three.js camera moves and GSAP scroll-scrubbed timelines (symmetrical, slow at both ends) |

Rule: one easing per property per animation. Spring physics are allowed only inside the Three.js governor (section 10) and never for DOM.

## 2. Duration scale

| Token | ms | Use |
|---|---|---|
| `--d-instant` | 80 | Hover colour, focus ring, pressed state |
| `--d-fast` | 160 | Toggles, chips, small opacity, tooltip |
| `--d-base` | 240 | Card lift, menu open, accordion, filter result swap |
| `--d-slow` | 400 | Section reveal, dialog, page transition cross-fade |
| `--d-cinematic` | 900 | Hero chapter changes, instrument rearrangement (scroll-scrubbed, so this is the scrub length in viewport fraction terms, see section 6) |
| `--d-opening` | 6000 max | The one-time opening; skippable from frame one (VERIFIED: Skip exists today) |

Distance scaling: translate distance per duration never exceeds 24 px at `--d-fast`, 40 px at `--d-base`, 64 px at `--d-slow`. Anything larger is a layout change and uses View Transitions, not transforms.

## 3. Entrance and exit behaviour

- Entrances: opacity 0 to 1 plus translateY 12 to 16 px (never scale under 0.96, never blur), `--ease-out`, `--d-slow` for sections and `--d-base` for items. Triggered once by IntersectionObserver at 15 percent visible with `rootMargin: 0 0 -10%`; elements already in the viewport on load are NOT animated (they render final state) so LCP content never fades in. Only content below the first viewport reveals.
- Exits: shorter than entrances (0.6 of the entrance duration), `--ease-in`, opacity only for anything leaving by navigation; translate only for dismissals the user caused (menu close, dialog close).
- Nothing animates `width`, `height`, `top`, `left`, `margin` or `padding`; only `transform`, `opacity`, `clip-path` and colour. Height changes (accordion) use `grid-template-rows: 0fr to 1fr`.
- Never animate the same element with CSS and JS at once (section 10).

## 4. Navigation transitions

- Cross-document View Transitions via Astro `<ClientRouter>`: default is a 240 ms opacity cross-fade on `::view-transition-old(root)` and `::view-transition-new(root)` with `--ease-linear`; the case title and cover carry `transition:name` and morph for 400 ms with `--ease-in-out` (VERIFIED: a title View Transition exists today).
- Back and forward: the morph runs in reverse automatically; nothing custom. The canvas on the home uses `transition:persist` so returning does not replay the opening (VERIFIED rule: no opening on return, hash, second visit or reduced motion).
- Fallback (no API): plain navigation, no JS curtain, no fake loaders.
- Within-page route state (archive query, tabs, dialog): no transition on the URL change itself; the result list swaps with a 160 ms opacity, items re-enter with the stagger from section 5 capped at 8 items.

## 5. Stagger rules

- Base stagger 40 ms, `--ease-out`, max 8 staggered items; items 9+ appear together with the 8th. Total stagger never exceeds 320 ms.
- Direction follows reading order (top-left to bottom-right); grids stagger by row index, not by DOM index, so wide rows do not ripple diagonally.
- Lists that re-sort or filter stagger only new entrants; survivors use FLIP via GSAP `Flip` or the View Transitions same-document API when it exists, otherwise no movement.

## 6. Scroll behaviour

- Native scrolling. No global smooth-scroll override; Lenis stays unused (VERIFIED: vendored but unused by the home). Justification required to add it: a measured need for scrub smoothness that CSS `scroll-timeline` and GSAP ScrollTrigger `scrub: 0.4` cannot meet, recorded in the PR.
- Pinned: only the home's instrument stage, one pin per chapter sequence, pin length 150 to 250 percent of viewport height per chapter, all driven by one GSAP ScrollTrigger timeline with `scrub: 0.4`. Nothing else on the site pins. Case pages: no pinning; the hero instrument parallaxes at most 6 percent of its height with `scroll-timeline` (CSS) and the reading progress bar is CSS `animation-timeline: scroll()` (no JS).
- Never pinned: navigation, footers, text columns, the archive, dialogs.
- Horizontal scroll sections: none.
- Scroll-driven motion maps progress to transform or opacity only; chapter copy swaps with 160 ms opacity, never typewriter effects.
- Scroll jacking (wheel capture, forced section snapping) is forbidden; `scroll-snap` may be used on the chapter stage with `proximity`, never `mandatory`.

## 7. Gesture and focus transitions

- Pointer drag on the instrument (VERIFIED: fine pointers today) uses direct manipulation at 1:1 while held, then a 400 ms `--ease-settle` return or seat on release; touch gets the same with a 10 px slop before a drag claims the gesture, and vertical swipes always scroll the page (touch-action: pan-y).
- Hover: colour and underline in `--d-instant`; card lift translateY -4 px and shadow in `--d-base`; no hover on touch (`@media (hover: hover)`).
- Focus: ring appears with no transition (0 ms) so it is never missed; `:focus-visible` only. Focus movement after dialog open and page transition is instant. Skip link slides in 160 ms.
- Press: scale 0.98 for `--d-instant`, released with `--d-fast`.

## 8. Loading transitions

- First paint: poster visible at once (no fade-in; it is the LCP). Canvas cross-fades over 400 ms when its first frame has drawn. If WebGL fails or is absent, nothing changes: the poster is the page.
- Deferred content (tiles, charts): reserve the box with aspect-ratio; swap in with 160 ms opacity. No skeleton shimmer loops; a static muted surface is the placeholder.
- Progress for the opening is a thin bar with `--ease-linear`; never a percentage counter.
- Loop videos start muted when 50 percent visible, pause when out of view; the first frame equals the poster so start is seamless.

## 9. Reduced-motion alternatives per pattern

| Pattern | Normal | `prefers-reduced-motion: reduce` |
|---|---|---|
| Opening | 6 s camera and seating, skippable | None; poster, title visible, 400 ms opacity only (VERIFIED behaviour today) |
| Section reveal | opacity + 16 px rise | opacity only, 240 ms |
| Page transition | cross-fade + title morph | instant swap (`@media` rule disables `::view-transition` animations) |
| Chapter scrub | pinned instrument timeline | no pin; chapters stack as static sections with the arrangement still (`assets/config-<state>.webp`, VERIFIED these exist) |
| Loops | autoplay muted | poster frame with a visible Play button |
| Hover lift | translate + shadow | colour change only |
| Stagger | 40 ms | 0 (items appear together) |
| Dialog | 240 ms scale 0.98 to 1 + fade | fade 120 ms |
| Charts | draw-on 400 ms | final state |
| Drag settle | overshoot | linear 160 ms |

A visible "Pause" and "Reduce motion" control exists on the home regardless of OS setting (VERIFIED: Pause exists) and stores the choice in `localStorage` with try/catch.

## 10. Animation ownership hierarchy

Order of preference; the first capable layer owns the property:

1. CSS (transitions, keyframes, scroll-timeline, view-transitions): all microinteractions, reveals, focus, hover, dialogs, page transitions, progress bars.
2. GSAP: timelines with more than two sequenced steps, scroll-scrubbed pins (ScrollTrigger), FLIP reorders, the opening's DOM choreography. GSAP never animates an element that has a CSS `transition` on the same property; the element gets `data-motion="gsap"` and a stylesheet rule `[data-motion="gsap"] { transition: none }`.
3. Three.js: only the instrument and future microsite objects, i.e. where depth, lighting or parallax of a real 3D form is the content. Three owns camera, materials and part transforms; it never positions DOM, and DOM never writes into the scene except through the single `stage.set(state, progress)` API driven by the GSAP timeline (one writer).
4. Remotion: offline renders only (tiles, recordings, OG videos); nothing from Remotion runs in the browser; its compositions reuse the easing tokens by importing `packages/tokens/motion.ts`.

Hard rule: no two systems animate the same property of the same element. The lint (`packages/motion/lint.ts`) greps for GSAP targets that also appear in CSS `transition` selectors and fails CI on overlap.

## 11. Lifecycle and cleanup rules

- Every island exports `mount(el): () => void`; the returned disposer kills GSAP timelines (`tl.kill()`, `ScrollTrigger.getAll().forEach(t => t.kill())` scoped by `gsap.context`), disconnects observers, removes listeners, cancels `requestAnimationFrame`, and disposes Three geometries, materials, textures and the renderer (`renderer.dispose()`, `forceContextLoss()` on unmount).
- Disposers run on `astro:before-swap`, on `pagehide`, and when the island leaves the viewport by more than one screen for 30 s (Three only; it remounts from the poster).
- Render loops run only while visible (IntersectionObserver + `visibilitychange`) and only while something changes (dirty flag); idle scenes draw zero frames.
- `ResizeObserver` drives canvas size with a 100 ms trailing debounce; DPR follows the governor in architecture.md section 7.
- Context loss: `preventDefault`, show poster, rebuild on restore, give up after two losses (VERIFIED: tests/evidence/gl-loss.cjs covers this today).
- Audio (VERIFIED: an audio manager exists) starts only on a user gesture, stops on `pagehide`, and persists its muted state.

## 12. Microinteraction table

| Component | Intent | Trigger | Duration | Easing | Notes |
|---|---|---|---|---|---|
| Button | confirm press | hover / press / release | 80 / 80 / 160 | out | colour + scale 0.98; focus ring instant |
| Card (catalogue row, tile) | invite | hover, focus-within | 240 | out | translateY -4 px, shadow token; loop starts at 50 percent visible, not on hover |
| Search (archive query bar) | respond | input (debounced 120 ms) | 160 result swap | linear | survivors stay, new rows stagger 40 ms up to 8; count text updates with no animation |
| Filters (kind tabs) | show state | click, arrow keys | 240 indicator slide | in-out | indicator is one element moving (FLIP), content swaps 160 ms |
| Menu | open / close | click, Escape | 240 / 160 | out / in | translateY 8 px + opacity; focus trapped; backdrop fade linear |
| Link (inline) | affordance | hover, focus | 80 | out | underline thickness or offset, no colour pulse |
| Accordion (case sections) | reveal | click, Enter | 240 | in-out | `grid-template-rows` 0fr to 1fr, chevron rotate 180 |
| Chart (facts, tables) | explain | enter viewport once | 400 | out | bars grow from baseline, lines draw via stroke-dashoffset, numbers do not count up |
| Preview (dialog `#<slug>`) | focus | click, deep link | 240 open / 160 close | out / in | scale 0.98 to 1 + fade; history owned explicitly (VERIFIED today) |
| Copy button | confirm | click | 160 then hold 1200 | out | label swaps to "Copied", icon check; live region announces |
| Zoom (case images) | inspect | click, Escape | 400 | in-out | View Transition morph of the image; backdrop linear |
| Sortable table header | state | click | 160 | out | arrow flips; rows reorder with FLIP, max 8 staggered |
| Reading progress | orient | scroll | continuous | linear | CSS scroll timeline only |
| Instrument arrangement buttons | rearrange | click, slider, arrow keys | 900 | camera | GSAP drives `stage.set`; buttons show pressed state in 80 ms |

## 13. Motion QA checklist

Frame pacing targets: desktop 60 fps with p95 frame time <= 20 ms and p99 <= 33 ms during the opening and every chapter scrub; mobile (iPhone 12 class, stated in the report) >= 30 fps with p95 <= 40 ms; zero long tasks over 100 ms after the poster paint; CLS contribution of any animation 0.

What to record (per PR touching motion, output to the evidence folder): a full-page scroll recording at 1440x900 and 390x844; the opening once with and once with Skip; `pace.json` p50/p95/p99 (port of `tests/evidence/pace.cjs`, VERIFIED to exist); the reduced-motion variant screenshots at the 8 widths; the keyboard-only pass video (Tab through the home and one case page); 200 percent zoom screenshots at 1280; a context-loss run; the throttled CPU (4x) run.

How to judge "preset-looking" motion (fail if two or more apply): everything on the page fades up from below with the same delay; scale-from-0.9 entrances; bouncy easings on text; typewriter or count-up numbers; parallax on more than one layer; a loader that counts percent; hover effects that move content under the cursor; motion that does not reference the project's content (CLAUDE.md rule: the animation must be about what the project is and found, VERIFIED); any element that moves without a reason an implementer can name in one sentence.

Pass criteria: targets met, recordings read by someone other than the implementer (CLAUDE.md mandatory independent visual QA), ownership lint clean, no `transition` and GSAP overlap, disposers verified by navigating home to case to home three times with no growth in `performance.memory` beyond 10 percent and no orphan `requestAnimationFrame` (checked by `tests/evidence/lifecycle.cjs`, VERIFIED to exist).
