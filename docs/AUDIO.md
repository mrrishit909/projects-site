# Audio policy, cue sheet and checks

Default: silence. A persistent Sound off/on control sits in the top bar on the home. Audio starts only on that click (a
user gesture); a remembered preference from the same session is applied on the first pointer down, never on load.
No files: every cue is synthesised in Web Audio at play time, so there is nothing to license and nothing to download.

## The manager (home.js `audio`)

One AudioContext created on first enable; one master gain (0 to 0.5 over 150 ms on enable, to 0 over 80 ms on
disable, then the context is suspended 400 ms later); at most 4 simultaneous voices; per-cue minimum spacing (click
90 ms, tick 70 ms, texture 400 ms, cue 600 ms) so a continuous scroll over the 31 tests plays at most 31 ticks and a
chapter crossing one cue; every voice has an attack and an exponential release; `visibilitychange` suspends and
resumes; the Pause control suspends; Replay and Skip never duplicate voices (the click is guarded by `intro.clicked`).

## Cue sheet

| Cue | Trigger (user-visible event) | Sound | Peak |
|---|---|---|---|
| click | the parts lock into the assembled register at 1.9 s of the opening (once per run) | sine 1900 to 855 Hz, 80 ms | 0.12 x 0.5 master = -24 dBFS |
| texture | the register unlocks into the exploded hero (once per run) | band-passed noise burst, 400 ms | 0.05 x 0.5 = -32 dBFS |
| cue | arriving in a new chapter (not during the opening); choosing an arrangement in the system chapter | two sines 523 + 784 Hz, 450 ms | 0.06 x 0.5 = -30 dBFS |
| tick | the hour input moves; a test pins in | sine 1300 to 585 Hz, 80 ms | 0.07 x 0.5 = -29 dBFS |

Rejected: a constant bed (the earlier home's drone), per-scroll-tick sounds, sounds on hover.

## Signal limits

Per-voice peaks above are below -1 dBTP by more than 20 dB; four voices at once sum to at most 0.15 (-16.5 dBFS).
These are digital-signal limits, not proof of safe listening levels; playback is conservative and the visitor holds the
control.

## Checks (PASS / FAIL / BLOCKED)

| Case | Status | How |
|---|---|---|
| first visit muted | PASS | tests/portfolio-check.cjs: the button starts aria-pressed=false, "Sound off" |
| enable, disable during sound | PASS | the suite toggles twice and reads the label; the code fades the master before suspending |
| replay, skip midway | PASS | click guarded once per run; Skip jumps the timeline so no voice is scheduled late |
| rapid repeated project selection | PASS by construction | cue spacing 600 ms, 4 voices; pace.cjs clicks six arrangements in 3 s |
| reverse scroll | PASS by construction | ticks only on a rising test count; chapter cues deduplicated by index |
| route return | PASS | a new document: no context survives navigation; preference reapplied only after a gesture |
| background / foreground | PASS by code path | visibilitychange suspends and resumes; not exercised by Playwright (cannot hide a tab) |
| audio unavailable | PASS | AudioContext creation is inside the enable handler; failure leaves the button at off |
| reduced motion | PASS | cues still gated by the control; the opening's click and texture fire in the short sequence |
| mute remains effective, state communicated | PASS | aria-pressed and the visible label |
| AUDITORY REVIEW | NOT PERFORMED | no listening pass happened in this session; the numeric envelope was checked, taste and synchronisation were not heard. The site ships muted by default, so this does not block the silent visual site. |
