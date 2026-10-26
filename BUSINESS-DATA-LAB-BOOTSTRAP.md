# Business Data Lab — corrected remote bootstrap
Version: 2026-10-26. Read this before the original START-HERE-PROMPT.md.

## Exact source location
- Repository: https://github.com/mrrishit909/projects-site
- Source branch: claude-business-data-directive-2026-10-26
- Directive directory: build-directives/business-data-lab/
- Original verified pack commit: fe5f79812a57816db6850cc8533e074e4c3ed36d
- README: build-directives/business-data-lab/README.md
- Master: build-directives/business-data-lab/MASTER-DIRECTIVE.md
- First project: build-directives/business-data-lab/projects/01-revenue-atlas.md
- Project manifest: build-directives/business-data-lab/LINE-COUNT-AND-HASHES.json

The directive is NOT at the repository root and is NOT on the default branch.
Use an explicit branch/ref when retrieving it. Absence on the default branch or at the root is not evidence that it is missing.
Do not search the laptop home folder, every repository, organizations or gists again.

If the cloud session opens the default branch, retrieve the specific remote branch or retrieve the files through GitHub's contents API with the ref above. Do not reset an existing checkout or overwrite another task's work.
On a verified REMOTE host, a read-only retrieval example is:
```bash
gh api 'repos/mrrishit909/projects-site/contents/build-directives/business-data-lab/MASTER-DIRECTIVE.md?ref=fe5f79812a57816db6850cc8533e074e4c3ed36d' -H 'Accept: application/vnd.github.raw+json'
```
Use the GitHub integration instead if the cloud environment supplies repository access without a gh CLI token.
Preserve the verified source commit and specification hashes in the build ledger.

## Operational corrections and precedence
This bootstrap supersedes only conflicting operational instructions about source location, permitted remote compute and model orchestration in the original pack. All business requirements, test gates, storage constraints, release rules and project scope remain applicable.

1. NO LAPTOP PROJECT STORAGE
Implementation must run in an actually remote environment. Do not create a local checkout, dependency cache, project database, generated report or source file on the laptop.
A local Claude CLI can retain prompts/tool payloads in its session logs; targeting GitHub APIs from that CLI does not provide a strict no-local-copy guarantee.
Do not use Remote Control of a local session as a substitute for cloud execution.
Do not inspect or modify the laptop's home directory or shell profile to bootstrap this work.

2. ALLOWED REMOTE COMPUTE
An Anthropic-hosted Claude Code cloud session, GitHub-hosted Actions runner or browser-only GitHub Codespace is permitted for transient execution.
Claude Code cloud normally runs on Anthropic-managed infrastructure; it is not automatically a GitHub-hosted machine.
The original project's phrase "only on GitHub-hosted compute" is narrowed to a durable-storage/CI preference: no laptop execution, all durable project deliverables committed or uploaded to GitHub, and GitHub Actions used for reproducible CI.
Remote temporary checkouts, dependency caches and test databases are allowed, but cannot be the only copy of completed deliverables.
Commit source and durable progress frequently; preserve larger irreplaceable outputs as GitHub release assets.
No new paid infrastructure, model credit purchase or budget increase is authorized by this clarification.

3. FABLE 5.1 AS THE BRAIN
Explicitly resolve and record the actual coordinator model.
Use Fable 5.1 as the main coordinator where the environment supports it.
If the outer cloud session cannot select Fable 5.1 but can actually invoke it as a subagent, use Fable 5.1 as the supervisory planning and review agent.
In that arrangement, the outer model performs transport, task dispatch and tool orchestration; Fable owns architecture, business-rule decisions, decomposition and acceptance decisions.
Record outer-session and supervisory model identities separately. Do not claim the outer session itself is Fable.
Delegate implementation to available entitled specialist models and have Fable review integrated results.
Do not assume an environment-variable string proves which model actually served a request.
The reported laptop ANTHROPIC_MODEL value is not evidence of the cloud environment's model configuration. Inspect the remote configuration without printing secrets.
Use supported current model selection; an explicit in-session model selection has precedence over a startup environment default.
If Fable cannot actually be invoked, perform useful source discovery and deterministic validation, then record the exact model blocker rather than fabricating Fable supervision.
Respect existing entitlement and spending controls; do not purchase or silently authorize additional credits.

4. BEGIN WITHOUT ANOTHER REPOSITORY DISCOVERY LOOP
Read the README, master and full project 01 specification from the exact directory above.
Use the master plus this bootstrap as the operating contract.
Do not modify the live portfolio just to make the directives easier to find.
Use an isolated remote branch. Inspect current repository instructions before edits.
Create the task queue, program-status.json, delegation-ledger.jsonl and verification-ledger.json in a scoped remote build directory.
If a dedicated business-data-lab repository already exists, inspect it before reuse. If creation/access is unavailable, continue on an isolated branch of an already authorized repository rather than treating a new repository as a mandatory blocker.
Keep the directive source files separate from application source.
Complete the first known-answer fixture and source-to-decision vertical slice before expanding the project.
Continue through all ten projects, delegated implementation, verification, individual websites and main-portfolio integration.
Do not request routine confirmation between milestones. Checkpoint genuine external blockers and continue unblocked authorized work.
Do not interpret this bootstrap as permission to bypass controls, expose credentials, purchase services or overwrite unrelated work.

## First status report
Report these observed facts briefly, then proceed:
- Actual remote execution environment.
- Exact source commit and directive directory.
- Actual outer and supervisory models.
- Working repository/branch and durable checkpoint location.
- First concrete task and its acceptance condition.
Do not replace execution with another broad search or a speculative budget estimate.

## Official references
- https://code.claude.com/docs/en/claude-code-on-the-web
- https://code.claude.com/docs/en/model-config
