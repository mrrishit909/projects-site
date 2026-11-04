# ATELIER X: environment audit (Phase 0)

Audited 2026-11-03, 21:44 to 21:55 EST, from the Claude Code CLI session in which the ATELIER X directive was pasted. Labels: VERIFIED (ran or inspected), INFERRED, PROPOSED, BLOCKED.

## Machine and runtime (VERIFIED)

| Item | Value |
|---|---|
| Hardware / OS | Apple M3 Pro, macOS 27.0.1 (Darwin 27.0.0), 595 GiB free of 926 GiB |
| Claude Code | 2.1.318; model set to Opus 5.5 for this session with `/model opus`, effort `high` |
| Model override warning | `ANTHROPIC_MODEL=anthropic/claude-3-5-sonnet-latest` is set in the shell environment; the CLI warned that new sessions use it while it is set. Not changed by me (owner's environment). Owner action: unset it or set it to the intended model before the next session. |
| Auth mode | No `ANTHROPIC_API_KEY` in the environment (count 0); Claude Code runs on the subscription login. No API charges can accrue from this session. |
| Node / npm / npx | v24.21.0 via nvm, npm 11.19.0 |
| Python | 3.15.0; `uv` present at `~/.local/bin/uv`; no pipx, no Homebrew |
| git / gh | git 2.54.0 (Apple); gh 2.102.0 logged in as `mrrishit909` (keyring), scopes `gist, read:org, repo, workflow`, https protocol |
| Codex | `codex-cli 0.166.0` on PATH (ChatGPT subscription; used with `--sandbox read-only`) |
| Browsers | Google Chrome installed; the `claude-in-chrome` MCP tools are available in this session; Playwright global status recorded in the addendum below |
| Rendering tools | Blender 4.5 at `~/Applications/Blender.app`; `ffmpeg`, `bun`, `pnpm` absent |
| Agent execution | Agent tool with background subagents and worktree isolation is available; six subagents plus one Codex process ran concurrently tonight without issue |

## MCP servers (VERIFIED from the session manifest)

Connected: claude-in-chrome, Claude Docs, Google Docs, Higgsfield (two servers; an earlier session recorded the free plan cannot generate media: INFERRED still true), Notion, Indeed, Gmail / Calendar / Drive (small-business plugin), Shopify, bio-research servers, pdf-viewer, and many `authenticate`-only stubs. Failed to connect: activecampaign (invalid config), definite (endpoint not found), etincel-nonfiction (connection closed), docusign (auth server incompatibility). None of the failed servers is needed for this program.

## Plugins and skills (VERIFIED)

User-level plugins at session start: ponytail 4.9.0, frontend-design 1.1.1, superpowers 7.0.1, codex 1.0.6, claude-hud 0.15.0, i-have-adhd 0.4.1, humanizer 3.1.0, social-media-skills 1.1.0, marketing-skills 2.14.0, last30days 3.31.0, gsap-skills 1.0.0. Added tonight: hyperframes (official marketplace `heygen-com/hyperframes`). Skills under `~/.claude/skills` and `~/.agents/skills` include gstack (clone at d4bef0a6, 2026-11-03), taste-skill (clone at b482f7a9), impeccable, ui-ux-pro-max, emil's three skills, remotion's two skills, skill-creator, find-skills, plus the owner's own website-playbook, new-project, five-tool-design-pipeline and others. Full disposition of the 22 named skills: `docs/skill-execution-matrix.md`.

Session hooks observed: ponytail (lean-code mode, full), an em-dash replacement hook (so these documents avoid dash characters by rule), and the Seal Copilot instructions (irrelevant here).

## GitHub access and the current portfolio (VERIFIED)

| Check | Result |
|---|---|
| `https://mrrishit909.github.io/` | 200 |
| `https://mrrishit909.github.io/projects/` (current portfolio, public repo `mrrishit909/projects`, branch `main`) | 200 |
| `https://mrrishit909.github.io/projects-site/` (the directive's "additional reference") | 200. Note: `projects-site` is the PRIVATE repository; its Pages site is publicly reachable. Possible only on a paid or Student-Pro plan (INFERRED). Owner should confirm this exposure is intended; nothing in the private repo's history should be assumed private once Pages serves it. |
| `https://github.com/mrrishit909` | 200 |
| Repository count | 245 owned repos: 219 public, 26 private, 0 forks, 0 archived (from the inventory lane, `gh api --paginate`) |

## Preserve existing work (directive 0.2), each item done tonight (VERIFIED)

1. Repository inspected: `~/projects-site`, remotes `origin` = `mrrishit909/projects` (public, serves Pages) and `private` = `mrrishit909/projects-site`.
2. Deployment pipeline: no `.github/workflows` in the repo; `python3 build.py` generates HTML which is committed; GitHub Pages serves `origin/main` as-is. Publishing rule in the repo's CLAUDE.md: push only to `private unified-portfolio`; never push `origin`.
3. Latest working commits recorded: public production `origin/main` = `85e89aabdf72`; private `unified-portfolio` = `cb85a0e89bf9` (local and remote in sync).
4. Existing content: 213 generated case-study folders with `project.json`, `featured.json` (four flagships), vendored Three.js / GSAP / Lenis / fonts, evidence folders under `~/projects-site-evidence/`.
5. Rollback strategy: the public site is untouched; the private branch is untouched; all ATELIER X work lives on the new local branch `atelier-x` (branched from `cb85a0e89bf9`). Rollback = `git switch unified-portfolio` (or delete `atelier-x`). No history rewrite, no force push, no deletion of any deployed site.
6. Dedicated working branch: `atelier-x` (local only tonight; not pushed).
7. Functioning applications preserved: nothing under any other project directory was modified.
8. No production deployment was changed; cutover requires explicit owner approval (directive 22).

## Local-storage policy (directive 0.3), applied (VERIFIED)

No new project directories, databases or asset dumps were created. Temporary files live in the session scratchpad. Durable outputs are Markdown and one JSON file under `~/projects-site/docs` and `data`. Tonight's installs: the hyperframes plugin (Claude plugin cache), `agent-browser` (global npm), `graphifyy` (uv tool environment). `agent-browser install` (a Chrome for Testing download) was NOT run; the installed Chrome can be used instead. `graphify install` (writes a global hook and CLAUDE.md section) was NOT run.

## Usage limits and potential costs (VERIFIED where stated, otherwise INFERRED)

- Claude Code: subscription usage only; the session reported ample token budget. No Anthropic API key is used.
- Codex: subscription; `codex exec` was run read-only, once, in the background.
- GitHub: free plan terms (INFERRED standard): Pages for public repos, Actions minutes free for public repos; the private repo's Pages site implies a paid or Student plan.
- Research platforms (GetLayers, Mobbin, SaaSFrame, Page Flows): partly login- or plan-gated; nothing was purchased and no account was created. Access limits are recorded in `docs/design-reference-atlas.md`.
- Higgsfield: free plan, cannot generate media (INFERRED from an earlier session note; not re-tested tonight).

## Blockers and owner actions

- BLOCKED until the owner decides: production cutover; any public description of the 26 private repos; whether the private repo's public Pages site is intended.
- Owner action: review `ANTHROPIC_MODEL` in the shell profile.
- Owner decision pending: creative direction pick (see `docs/creative-direction.md`) and architecture approval (see `docs/architecture.md`).

## Addendum: tonight's installs and remaining checks

(appended from the install log at the end of the window)

Install log, 21:46 EST (VERIFIED):

- hyperframes: `claude plugin marketplace add heygen-com/hyperframes` succeeded; `claude plugin install hyperframes@hyperframes` succeeded (version 0.9.10, scope user). The CLI noted that about 84 files in the marketplace clone are Git LFS pointers (media assets); skills themselves are plain text and loaded. Not needed for the skills; `git lfs pull` is available if the assets are ever wanted.
- agent-browser: `npm install -g agent-browser` installed 0.41.2 and `agent-browser --version` answers. npm reported that its postinstall script was NOT run (npm's `allowScripts` policy), so the native binary download did not happen; the JS launcher still runs. Decision deferred to the owner: allow the script once (`npm install -g --allow-scripts=agent-browser`) or keep using the `claude-in-chrome` tools and Playwright, which already cover browser QA. Not run yet.
- graphify: `uv tool install graphifyy` installed 0.9.102 with two executables, `graphify` and `graphify-mcp`, in `~/.local/bin`; `graphify --help` answers. `graphify install` (global hook + CLAUDE.md edits) was not run.
- Playwright 1.64.0 is installed globally (used by the existing check suite and evidence scripts).
- Codex adversarial review: `codex exec --sandbox read-only` exited 1 at 21:51 with no answer written: ChatGPT usage limit reached, resets 2026-11-04 01:41 EST (BLOCKED). The error text and the retry plan are in `docs/codex-architecture-review.md`.
