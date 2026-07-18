# FDAI - Copilot Instructions

Autonomous cloud operations control plane - an **AIOps** approach whose initial verticals
are **Resilience** (disaster recovery and chaos/resilience testing), **Change Safety** (safe
change and drift remediation), and **Cost Governance** (FinOps). The same architecture
applies to other AIOps domains (posture management, SRE/SLO, etc.), which are future scope.
Goal: minimize human intervention by resolving most events deterministically and using LLMs
only for the residual ambiguous cases.

> Source vision: `deep-plan/autonomous-operations.md` (maintainer-only, **not tracked in
> this repo** - do not treat this as a repo link). This repo implements that plan; keep the
> design principles below intact.

**How to use this file:** this is the short-form hub. Each linked
`instructions/*.instructions.md` file is authoritative for its topic - open it when in
doubt. Items marked **(MUST)** are hard requirements; conflicts resolve in favor of the more
specific sub-instruction file. The [roadmap](../docs/roadmap/README.md) expands these
principles into a phased engineering plan.

## Language Policy (MUST)

- **FDAI is fully bilingual: English and Korean are both allowed in any
  natural-language text anywhere in the repository** - source comments, docstrings,
  string literals, logs, error messages, tests, docs, commit messages, GitHub issues,
  and `.github/**`. There is **no english-only gate**; Korean is never a defect on the
  basis of being Korean.
- **Two tooling constraints remain** (not about language choice): identifiers,
  filenames, and branch names MUST be ASCII (`a-z A-Z 0-9 _ - .`), and punctuation MUST
  be ASCII (enforced by `scripts/quality/repository/check-punctuation.sh`). Write Korean in comments and
  string **values**, never in a name or a path.
- **Machine records SHOULD stay English** - audit entries, event payloads, serialized
  verdicts, log keys, rule ids, and config keys are machine-consumed (replay,
  correlation, cross-fork search), so keeping them English is a strong recommendation,
  not a hard gate. Localize the labels around a machine record, not the record itself.
- Structured bilingual delivery still uses `foo.md` + `foo-ko.md` doc pairs and
  English-source `.ko.json` catalogs with mandatory English fallback; the Bragi narrator
  renders in the operator's locale.
- Rationale and full rules: [instructions/language.instructions.md](instructions/language.instructions.md).

## Implementation Focus (MUST)

- **FDAI's implemented target is Azure.** All engineering work - provider adapters,
  event sources, executor identity, rule collectors, and the deployment topology - targets
  Azure first.
- **Non-Azure providers (AWS, GCP, and multi-cloud expansion) are TBD** and out of scope
  until an Azure baseline is proven. Any reference to a non-Azure CSP in the roadmap or
  design docs is a **deferred future item**, not a build commitment.
- **The CSP-neutral abstractions are preserved as design principles**, not delivery goals:
  the core engine stays behind provider adapters, rules normalize to a CSP-neutral schema,
  and vendor SDK calls sit behind interfaces - so a future non-Azure target can be added
  without a core rewrite. But no adapter beyond Azure is built until it is explicitly
  scoped in a future phase.
- Phase 4 (multi-cloud scale-out) is **TBD in this roadmap** - its non-multi-cloud content
  (continuous measurement, pattern-library growth, model cost/quality tracking, scalability)
  applies to Azure as-is.

## Core Principles (short form)

1. **Deterministic-first** - rules/policies/checklists resolve most cases; reserve LLM
   inference for the residual ambiguous minority.
2. **Confidence tiering (T0/T1/T2)** - route by certainty: **T0** deterministic
   (~70-80% coverage), **T1** lightweight similarity reuse (~15-20%), **T2** frontier-model
   reasoning for novel cases only (~5-10%). These percentages are design targets, not
   measured results.
3. **LLM quality gate** - T2 output must pass a mixed-model cross-check, a deterministic
   verifier, and rule grounding (abstain if unsupported) before it can execute. The model
   generates; **execution eligibility is granted by deterministic verification**, never by
   the model alone.
4. **Risk-gated autonomy** - low risk auto-executes; high risk goes to human-in-the-loop
   (**HIL**). Autonomy is never unconditional.
5. **Event-driven** - wake on events, scale-to-zero when idle; no constant polling.
6. **Policy, state, audit as code** - policy-as-code (OPA), tracked state, and a full
   audit-log entry for every autonomous action.
7. **Shadow before enforce** - new actions ship judge-only in shadow mode, then are promoted
   to enforce explicitly.
8. **Living rules** - the rule catalog is continuously collected, validated, and updated so
   the deterministic layer never goes stale.

## Detailed Guides

- [instructions/language.instructions.md](instructions/language.instructions.md) - language & naming rules.
- [instructions/generic-scope.instructions.md](instructions/generic-scope.instructions.md) - customer-agnostic scope and fork model.
- [instructions/architecture.instructions.md](instructions/architecture.instructions.md) - 3-tier trust routing, control loop, rule catalog.
- [instructions/agent-pantheon.instructions.md](instructions/agent-pantheon.instructions.md) - the 15-agent pantheon roles/permissions and the MUST rules for changing any `src/fdai/agents/**` code (auto-loads when editing agent code).
- [instructions/app-shape.instructions.md](instructions/app-shape.instructions.md) - deployment topology and anti-patterns.
- [instructions/coding-conventions.instructions.md](instructions/coding-conventions.instructions.md) - code style, safety, and testing rules.
- [instructions/documentation-style.instructions.md](instructions/documentation-style.instructions.md) - required layout for every markdown doc (Tier A entry points, Tier B reference, Tier C subsystem READMEs). Full authoring reference in the [documentation-writing skill](skills/documentation-writing/SKILL.md).
- [docs/roadmap/fork-and-sequencing/downstream-fork-guide.md](../docs/roadmap/fork-and-sequencing/downstream-fork-guide.md) - procedural walkthrough for fork maintainers: Day-1 checklist, 9 seam recipes (LLM adapters, OperatorMemoryStore, HilRejectMaterializer, WebSearchProvider, HilChannel, ScopeResolver, Critic + Judge debate, rule catalog, Rego overlays), upstream sync, and anti-patterns.

## Generic-Only Scope (MUST)

- This repo is the **general-purpose, customer-agnostic** control plane. It must contain
  **no customer-specific information** of any kind: no customer or company names, tenant/
  subscription IDs, resource names, endpoints, credentials, private data, or bespoke rules.
- **Per-customer customization lives in a separate forked repo**, never here. Keep this
  codebase reusable across any Azure tenant (non-Azure targets are TBD, see
  [Implementation Focus](#implementation-focus-must)). Forks customize by **dependency
  injection** (registering implementations at the composition root), never by editing core.
- Full rule: [instructions/generic-scope.instructions.md](instructions/generic-scope.instructions.md).

## Non-negotiables

- Never hardcode secrets, connection strings, tenant/subscription IDs, resource names, or
  customer identifiers; load them from environment or a secret store at runtime.
- Every autonomous action needs all four: a stop-condition, a rollback path, a blast-radius
  limit, and an audit-log entry. Missing any one means the action is incomplete.
- Default new actions to **shadow mode** (judge and log only); promote to enforce explicitly.
- Deliver actions as **remediation PRs** (GitOps), not out-of-band changes - audit and
  rollback come for free.
- Prefer OSS and CSP-neutral abstractions (OPA, Terraform) over vendor lock-in - the
  Azure implementation still sits behind these abstractions so a future non-Azure target
  (TBD) does not require a core rewrite.
- Customize per-customer via **dependency injection** at the composition root, never by editing
  core (see [instructions/generic-scope.instructions.md](instructions/generic-scope.instructions.md)).
- **Docs-first, docs-after**: read the relevant design docs (`instructions/*` and
  [docs/roadmap](../docs/roadmap/README.md)) before writing code, and update the affected docs
  in the same PR after changing code. Docs and code never drift.
- Validate at system boundaries only; do not add defensive checks for impossible states.
- When opening a GitHub issue, apply the domain labels from the
  [CONTRIBUTING label catalog](../CONTRIBUTING.md#opening-issues) - at least one
  `area:` plus a type, adding `tier:` / `vertical:` / safety / cross-cutting
  labels when central. Issues never carry customer values.
- When you work on or review any GitHub issue, you MUST add a comment recording
  what was done, found, or why no change was needed - even for "already
  implemented" or "won't fix". If the issue was **registered by someone other
  than the acting maintainer**, also apply the `review-needed` label instead of
  self-closing it, so the author does a confirmation pass. See
  [Working on issues](../CONTRIBUTING.md#working-on-issues).
- Do not claim performance multipliers or other quantified gains without a stated, measured
  baseline.

## Repo Hints (agent-facing)

- **Pre-commit gate (single entry)**: run `scripts/verify.sh` (Ruff + strict mypy + fast
  text gates) or `scripts/verify.sh --full [<path>]` to include pytest. Individual
  `scripts/check-*.sh` remain as the CI-side primitives.
- **Runtime and generated artifacts (do not hand-edit)**: `resolved-models.json`,
  `resolved-models-local.json`, `infra/dev.plan`, `infra/terraform.tfstate*`,
  `alembic/versions/*` (schema migrations, append-only), and every `__pycache__/`. Treat
  these as build outputs; regenerate them via their tooling instead of editing.
- **Communication style with the maintainer** (tone, Korean casual, completion timestamps,
  no confirmation questions during autonomous runs) lives in the maintainer's user memory,
  not in this repo. Follow it verbatim when it is loaded; do not re-derive it from these
  instructions.
