# Security and Privacy Review (Agent M)

Date: 2026-11-03, 21:53 to 21:58 EST (hard stop). Branch: atelier-x (remotes: origin = public mrrishit909/projects, private = mrrishit909/projects-site). Tracked files: 4852. Scope: read-only review of /Users/rishitmathurrishit/projects-site. Each check is labeled VERIFIED (command shown) or BLOCKED/not run (time budget). No secret values are printed anywhere in this file.

## 1. Secret scan of tracked tree
VERIFIED: `git ls-files -z | xargs -0 grep -nIE 'sk-[A-Za-z0-9]{10,}|sk-proj-|ghp_[A-Za-z0-9]{20,}|github_pat_|AKIA[0-9A-Z]{12,}|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY|xox[baprs]-|AIza[0-9A-Za-z_-]{30,}'` and `git ls-files | grep -E '(^|/)\.env|\.pem$|\.key$'` and `cat .gitignore`.

Hits (masked):
- cloud-finops-optimizer/demo/scenario.json:33, prefix `AKIA` + `IOSF****`. This is the AWS documented example key, already allow-listed by name in publish.sh line 19 to 20. Info.
- publish.sh:17, 19, 20: the guard's own regex and allow-list. Not a secret. Info.
- labs/pipeline-observatory/assets/index-DAq-bZzb.js:42: VERIFIED false positive at 21:56 (`grep -oE '.{25}(github_pat_|ghp_...).{10}'`): the line holds the app's own secret-redaction regexes (`/\bghp_[A-Za-z0-9]{20,}\b/g, /\bgithub_pat_...`), i.e. patterns, not tokens. Info.
- No tracked .env, .pem or .key files. VERIFIED clean.

Finding S1 (Medium): .gitignore does not cover `.env`, `.env.*`, `node_modules/` or package-manager caches. It only lists `__pycache__/`, `.DS_Store`, `motion/.sheets/`, `.impeccable/`, `.taste-skill/inspect/`. Expected: a defensive ignore list so a stray `git add -A` cannot stage a credential file or a dependency tree. Actual: only publish.sh's runtime check stands between a tracked .env and the public remote, and that check does not run on `git push private`. Correction: append `.env`, `.env.*`, `*.pem`, `*.key`, `node_modules/`, `.npm/`, `.cache/`, `data/atelier-inventory.json` to .gitignore.

## 2. Private-path leakage in generated HTML
VERIFIED: `grep -lE '/Users/|rishitmathurrishit' index.html all.html */index.html | wc -l` = 0. No absolute paths and no local username in any generated page. Clean.

## 3. Personal data exposure
VERIFIED: `grep -ohE '<email regex>' index.html all.html */index.html | sort | uniq -c` and a phone regex over the same files.
- One e-mail address, domain yahoo.com, local part masked `r***`, appears 2 times across the public HTML (the copy-email control on the home page). This is the intended contact address. Info.
- No phone numbers found. Clean.
- The GitHub noreply address in publish.sh is not in HTML and is already public by design. Info.

## 4. Vendored dependency versions
VERIFIED: `head -c 600 vendor/<lib>/*.js | grep -oE '[0-9]+\.[0-9]+\.[0-9]+'`; `npm view three version`, `npm view gsap version`, `npm view lenis version`.

| Library | Vendored | npm latest | Gap |
|---|---|---|---|
| GSAP (gsap.min.js, ScrollTrigger.min.js) | 3.13.0 | 3.15.1 | two minor versions behind. Low |
| Lenis | 1.3.27 | 1.3.27 | current (and unused by the home per CLAUDE.md). Info |
| Three.js (tree-shaken module, no version string in header) | r170 per CLAUDE.md and docs/BUILD-THREE.md | 0.187.0 (r187) | 17 releases behind. Low: the bundle is limited to the symbols instrument.js uses and loads no remote content; still, record the revision in the bundle header so future audits do not depend on docs |

Advisory lookup (`gh api "advisories?ecosystem=npm&affects=three@0.170.0"` etc.): not run, time budget. Treat as open until run; none of the three libraries has a widely published RCE class advisory to my knowledge, but verify.

## 5. publish.sh guards
VERIFIED by reading the script. Guards present: (a) refuses if any tracked `.env` is present; (b) greps the entire history (`git log -p HEAD`) for a secret regex covering Anthropic, OpenAI, GitHub PAT, gh*_ tokens, AWS AKIA, PEM headers, with the AWS example key allow-listed; pipefail-safe form; (c) refuses tracked files over 49 MB; (d) token read from the keychain via `git credential fill`, never echoed.

Gaps:
- P1 (Medium): publish.sh pushes `HEAD:main` to `origin`. In this repository `origin` is the PUBLIC Pages repo, while the project rule since 2026-10-19 is private-only. Running `./publish.sh . projects` here by habit would publish the private branch. Correction: add at the top `if [ "$(git remote get-url origin)" = https://github.com/mrrishit909/projects.git ] && [ "$(git branch --show-current)" != main ]; then echo STOP; exit 1; fi`, or better, make the script refuse when a remote named `private` exists unless `FORCE_PUBLIC=1`.
- P2 (Medium): no check for private-inventory content (see section 8). Correction: add `if git grep -lE '"visibility": *"private"|"private": *true' -- 'data/*.json' >/dev/null; then echo "STOP: private repo inventory is tracked"; exit 1; fi`.
- P3 (Low): `.env` match is exact; `.env.local`, `.env.production`, `*.pem`, `*.key`, `id_rsa` are not covered. Correction: widen to `(^|/)\.env(\..*)?$|\.pem$|\.key$|(^|/)id_(rsa|ed25519)$`.
- P4 (Low): no `node_modules/` check; a 49 MB threshold is per file, so a tracked dependency tree under the limit passes. Correction: `git ls-files | grep -q '^node_modules/' && exit 1`.
- P5 (Info): secret regex does not include Slack `xox[baprs]-` or Google `AIza` prefixes. Add them.

## 6. Supply chain of tonight's installs
Based on the task brief plus a local check (`npm ls -g agent-browser` printed nothing, so the global install path was not confirmed in this session; hyperframes plugin files were not located under ~/.claude/plugins in the two paths probed). Assessment:

- hyperframes Claude plugin (skills only, no hooks). Residual risk Low: skill files are prompt text, but they execute with the agent's authority and can steer it into running commands. Rule: read every SKILL.md once before first use; re-read after any plugin update; keep it out of auto-loading in sensitive repos.
- agent-browser npm 0.41.2 (postinstall downloads a release binary). Residual risk Medium: a postinstall fetch means the artifact you run is not the artifact npm audited, and a compromised release asset or redirect would run on the Mac with your user's permissions. Rule: pin the exact version in any lockfile or `-g` install command (`agent-browser@0.41.2`, never a range), record the sha256 of the downloaded binary now (`shasum -a 256 $(npm root -g)/agent-browser/bin/*` or wherever it lands) and compare on the next install, prefer running it inside the browser sandbox profile, and inspect `npm view agent-browser@0.41.2 scripts` before each upgrade.
- graphifyy via uv (its `install` subcommand would add a PreToolUse hook and edit CLAUDE.md; deliberately not run). Correct decision. A PreToolUse hook executes before every tool call and can read or rewrite commands; a CLAUDE.md edit changes agent behaviour in every session. Rule: never run a third-party `install` subcommand that touches `~/.claude/settings*.json` hooks or any CLAUDE.md; if its features are wanted, add the hook by hand after reading the script it would invoke, and keep the diff in version control.

Cross-cutting rule: no tool installed tonight should be able to write to this repository's `data/` or `docs/` directories unattended; run them from a separate working directory.

## 7. GitHub Pages deployment hardening
VERIFIED: `ls .github/workflows` (none exist), `grep -c Content-Security-Policy index.html` = 0, grep for cdn/unpkg/jsdelivr/googleapis URLs in index.html = none.

- No Actions workflows: good. The site is built locally and the HTML is committed, so no secret ever needs to exist in GitHub Actions. Keep it that way; if a workflow is ever added, use `permissions: contents: read` plus `pages: write` and `id-token: write` only on the deploy job, and pin every `uses:` to a full commit SHA, not a tag.
- No CDN scripts or stylesheets: all JS and fonts are vendored, so SRI is not applicable today. Rule: if a CDN URL is ever introduced, add `integrity=` and `crossorigin="anonymous"` and pin the exact version in the URL.
- No CSP (Low): add `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data:; media-src 'self'; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'none'">` to the templates. `'unsafe-inline'` for scripts is needed only because the home carries an inline forwarding script; move it into home.js and drop that token. `frame-ancestors` is ignored in meta form, so clickjacking protection is a Pages limitation, not a fix you can ship here.
- Branch hygiene (Medium): the public repo's `main` must never receive a merge from a branch that carried private material. Enable branch protection on `main` of mrrishit909/projects with required review, and run publish.sh's guards as a pre-push hook on that repo.
- Add `.nojekyll` if not present so Pages serves `_`-prefixed assets unchanged (not security, but avoids silent 404s).

## 8. data/atelier-inventory.json (private repo names)
VERIFIED: `git ls-files --error-unmatch data/atelier-inventory.json` (untracked), `git check-ignore -v` (not ignored), `python3 -I` parse (list of 245 records with fields id, name, repo_url, visibility, kind, description, language, topics, pushed_at, homepage, pages_url, demo_status, product_group, portfolio_eligible, standalone_site_candidate, standalone_reason, has_case_study, featured, privacy, evidence), 26 records with `"visibility": "private"`, `grep -n atelier-inventory build.py publish.sh *.js` = no reader (build.py reads data/github.json only).

Finding I1 (High if committed, currently Medium): the file is untracked and not ignored, sits beside a tracked data file, and nothing in build.py or publish.sh distinguishes it. A `git add -A`, `git add data/`, or an editor's auto-stage will track it; from there the private branch (acceptable, private remote) and later any merge or cherry-pick into `main` or a push to `origin` publishes 26 private repository names, URLs, descriptions, languages and last-push dates. The names alone reveal client and unreleased work. The build does not read it today, so the HTML is clean; the risk is the repository, not the pages.

Rules to adopt:
1. Ignore it: add `data/atelier-inventory.json` (or better, `data/*-inventory.json`) to .gitignore tonight. Preferred: move the file out of the repository entirely to `~/projects-site-evidence/atelier-2026-10-25/inventory/`, which is already the convention for review artefacts.
2. Guard it: publish.sh and a pre-push hook on `origin` refuse when any tracked file contains `"visibility": "private"` (section 5, P2).
3. If build.py ever consumes it, filter at load time to `visibility == "public" and portfolio_eligible` and emit nothing else, and assert in tests/portfolio-check.cjs that no private repo name from the file appears in any generated HTML.

## Findings summary by severity
| Severity | Count | Items |
|---|---|---|
| Critical | 0 | |
| High | 0 (1 latent) | I1 becomes High the moment the inventory is tracked |
| Medium | 4 | S1 .gitignore gaps; P1 publish.sh targets the public origin; P2 no private-content guard; I1 inventory untracked and unignored; Pages branch hygiene |
| Low | 4 | GSAP two minors behind; Three.js r170 vs r187 with advisories not run; P3/P4 publish.sh pattern gaps; no CSP |
| Info | 6 | AWS example key allow-listed; publish.sh self-matches; labs bundle hit is the app's own redaction regex; one intended contact e-mail; Lenis current; no Actions, no CDN |

Not run: GitHub advisory API queries for three, gsap, lenis; verification of the agent-browser install path and binary hash.

## Top three actions
1. Tonight, before any further commit: add `data/atelier-inventory.json`, `.env`, `.env.*`, `*.pem`, `*.key`, `node_modules/` to .gitignore, or move the inventory file out of the repository.
2. Harden publish.sh: refuse when a `private` remote exists unless explicitly forced, refuse when any tracked JSON contains `"visibility": "private"`, widen the .env and key-file patterns, add xox/AIza prefixes.
3. Run the two deferred checks: `gh api "advisories?ecosystem=npm&affects=three@0.170.0"` (and gsap@3.13.0, lenis@1.3.27), and the one-line triage grep on labs/pipeline-observatory/assets/index-DAq-bZzb.js; then schedule the GSAP and Three.js bumps with the usual portfolio-check evidence run.
