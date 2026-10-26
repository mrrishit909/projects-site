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

## Failure handling (corrected 2026-10-26, D-04)

`start()` creates the context inside a try and returns false on failure; `set(true)` awaits `resume()` and reports
"Sound on" only when the context's state is running; otherwise the control stays "Sound off", a short note is written to
the page's live region ("Sound is not available in this browser" or "Sound could not start; it stays off"), and no
preference is stored. `resume()` on returning to the foreground is refused while the page is paused.

## Checks

Runtime verification (the suite exercised the path) is kept apart from code inspection (the path was read, not run).

| Case | Runtime | Code inspected | Evidence |
|---|---|---|---|
| first visit muted | VERIFIED PASS (suite: the control starts aria-pressed=false) | yes | portfolio-check.txt |
| enable on a gesture; the label changes only once the context runs | PENDING (suite audio block on the candidate) | yes | |
| AudioContext creation throwing | PENDING (suite: stubbed constructor) | yes | |
| resume refused | PENDING (suite: stubbed resume) | yes | |
| disable during sound (fade, then suspend) | PARTIAL (the suite toggles and reads the control; the fade is not measured) | yes | |
| replay, skip midway (no duplicate voices) | code inspected only | yes: the click is guarded once per run; Skip jumps the timeline | |
| rapid repeated toggling and selection | PENDING (suite: six rapid toggles end consistent); cue spacing and the four-voice cap are code inspected | yes | |
| reverse scroll (ticks only on a rising count) | code inspected only | yes | |
| route return (a new document has no context) | code inspected only | yes | |
| background then foreground; foreground while paused does not resume | PENDING (suite dispatches visibilitychange while paused) | yes | |
| audio unavailable (no AudioContext) | PENDING (suite) | yes | |
| reduced motion | code inspected only (cues still gated by the control) | yes | |
| mute effective, state communicated | PENDING (suite: aria-pressed and the label; the live-region note) | yes | |
| AUDITORY REVIEW | NOT PERFORMED | | no listening pass was possible in this environment; the envelope was checked numerically; taste, synchronisation, harshness, clicks and interference with reading were not heard. The site ships muted by default. |
