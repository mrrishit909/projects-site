# Research rationale and prompting decisions
Date: 2026-11-02. This is a design/specification deliverable, not proof that applications exist.

## Project usefulness
The selected problems correspond to documented business workflows rather than asserted market demand. APQC describes end-to-end receivables, collections, procurement, delivery and finance measurement. FinOps covers allocation, unit economics and SaaS/license decisions. Stripe documents proration complexity. IBM describes contract obligations/lifecycle and maintenance planning. Shopify documents reverse fulfillment. DOE explains intensity versus total energy. OPM describes structured job-related assessment. NIST describes privacy program mappings. Microsoft documents access review campaigns. Google OR-Tools documents constrained routing. GAO documents cost/schedule control methods.

These references support relevance and implementation discipline. They do not establish that a new standalone SaaS is commercially validated or that synthetic recommendations will yield real business savings. PriceLab and SchemaShift are original project syntheses using explicit economics/statistical and migration-reconciliation methods rather than copies of a referenced commercial product.

## Prompt engineering learned and applied
- Define success and give executable checks: each project has a decision, observable workflow and hand-calculated acceptance example.
- Use structured sections to separate authority, context, project data and execution instructions. The prompt uses XML-style boundaries and distinct project IDs.
- Decompose long-running work into initialized state and incremental implementation, with source commits, evidence and exact resume records.
- Keep context focused: one active project, task-scoped inputs and summaries rather than every project/log in every agent context.
- Delegate using actual model controls; full model IDs and per-invocation family aliases have different support. Require actual resolved model evidence.
- Require user-facing progress: terminal output describes real tasks, model assignments, commits, run statuses and evidence.
- Use deterministic tools/tests for hard invariants instead of expecting strong wording to guarantee correctness.
- Remove routine permission pauses within scope while preserving external permissions, entitlement and resource limits.
- Avoid prescribing hidden chain-of-thought; request concise decisions, assumptions and evidence instead.
- A native local terminal client may keep logs. Prohibit local PROJECT files and use remote execution, but do not pretend that guarantees zero client/OS writes.

## Design-library findings and access status
| Library | Inspected evidence | Constraint applied |
|---|---|---|
| GetLayers | Public homepage and docs at https://www.getlayers.ai/ and https://www.getlayers.ai/docs | Templates/prompts/source differ; source access depends on entitlement. Docs restrict redistribution of original source/prompts. Do not upload restricted source to public repositories. Templates are not automatically shipped-product proof. |
| Mobbin | Public homepage https://mobbin.com/ describes shipped app/web references | No claim of inspecting every screen or a private flow. Claude must inspect the selected accessible reference at build time. |
| SaaSFrame | Public homepage https://www.saasframe.io/ lists SaaS products and page types | Choose the relevant actual product/page and record the observed pattern; do not infer an interaction from a thumbnail alone. |
| Pageflows | Fetch attempts to bare and www domains failed/403 | No claim of having watched its recordings. Use authorized access if available or public shipped alternatives. |
| Component Gallery | Public homepage https://component.gallery/ links real design systems and component examples | Inspect underlying documentation/code for actual behavior and license, not merely the directory label. |
| CollectUI | Current public homepage https://collectui.com/ presents curated inspiration | Public homepage alone does not prove each entry shipped. Require a deployed product/source before accepting a reference. |

No product screenshots or private UI-library assets were downloaded or redistributed in this pack. Shipped-screen evidence collection is assigned to Claude at implementation time, with provenance and access classification. The prompt does not claim this task completed that later visual audit.

## Authoritative references consulted
Prompting/agents:
https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-1
https://code.claude.com/docs/en/best-practices
https://code.claude.com/docs/en/sub-agents
https://code.claude.com/docs/en/model-config
https://www.anthropic.com/research/effective-harnesses-for-long-running-agents
https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs

Business and methods:
https://www.apqc.org/How-Should-Order-to-Cash-And-Accounts-Receivable-Performance-Be-Measured-And-Improved
https://www.apqc.org/How-Should-Procure-to-Pay-And-Accounts-Payable-Performance-Be-Measured-And-Improved
https://www.apqc.org/What-are-the-key-steps-involved-in-the-purchasing-process
https://www.apqc.org/What-Is-Procurement-Cycle-Time
https://www.apqc.org/What-Are-the-Key-Indicators-to-Monitor-for-Financial-Flow
https://www.finops.org/framework/
https://www.finops.org/framework/capabilities/unit-economics/
https://www.ibm.com/think/topics/contract-lifecycle-management
https://www.ibm.com/think/topics/what-is-preventive-maintenance
https://docs.stripe.com/billing/subscriptions/prorations
https://support.google.com/google-ads/answer/12003020?hl=en
https://shopify.dev/docs/apps/build/orders-fulfillment/returns-apps/manage-reverse-fulfillment-orders
https://www.apqc.org/resources/benchmarking/open-standards-benchmarking/measures/finished-product-first-pass-quality
https://www.energy.gov/cmei/overview-energy-intensity-indicators
https://www.energy.gov/cmei/ito/better-plants-0
https://www.opm.gov/policy-data-oversight/assessment-and-selection/other-assessment-methods/structured-interviews/
https://learn.microsoft.com/entra/id-governance/manage-access-review
https://www.nist.gov/privacy-framework/using-privacy-framework-11
https://developers.google.com/optimization/routing/vrptw
https://www.gao.gov/products/gao-20-195g

Current portfolio instructions inspected remotely:
https://github.com/mrrishit909/projects-site/blob/unified-portfolio/CLAUDE.md

## Verification limits
verify_spec.py checks the twenty project IDs, expected sections, unique slugs, structured prompt boundaries and arithmetic in the twenty worked examples. VERIFICATION.json records the exact prompt SHA-256. It does NOT validate unbuilt software, external integrations, visual quality or live deployment. Those are required later build gates.

## Follow-up: 22 required upstream projects
The user changed the policy from zero local project-related writes to minimum necessary local writes and explicitly authorized installation/use of all 22 named tools. Their short links were tested. Seven LinkedIn interstitials exposed exact GitHub destinations; the remainder were not resolved by the browsing tool. Canonical upstreams were corroborated separately, and all 22 upstream README.md files were retrieved through GitHub. The authoring README blob hashes and link status are recorded in SKILLS-REGISTRY.json. These are README observations, not full security audits, installation tests or executable commit pins.

The original list mixes skills, plugins, CLI tools and frameworks. Ponytail is a minimal-code/reuse workflow, not a requirement to suppress all output. Codex's official plugin uses an existing local Codex runtime/authentication; it does not automatically move work to GitHub. The plugin documents a potentially expensive repeated Stop/review gate, so the prompt chooses bounded explicit reviews. HUD has actual Node/Claude version requirements. HyperFrames and Remotion need distinct rendering runtimes. Their heavy work is assigned to remote runners; necessary native terminal integration remains within the new limited local-write permission.

Remotion's agent skill pack is remotion-dev/skills and its framework is remotion-dev/remotion; both READMEs were retrieved. The social-media-skills canonical candidate is charlie947/social-media-skills, not a random similarly named pack. Exact original short-link checks remain a setup task where resolution was unavailable. No quoted popularity/star counts were relied on.

Primary sources: every https://github.com/<owner/repo> address in SKILLS-REGISTRY.json, plus https://github.com/remotion-dev/remotion . A secondary matching list helped identify labels but was not used as executable installation authority: https://programmier-workshops.de/blog/22-claude-code-skills-build-design-research-marketing/ . Claude must inspect actual current installation docs, manifests and scripts before setup, resolve actual repository commits and test actual invocation.

This amendment assigns installation, smoke checks, real per-purpose use and evidence; it does not claim the 22 tools are installed or operational on the user's machine yet. Public posting is not authorized by creating marketing/social drafts.
