---
description: "Use when editing source, tests, scripts, infrastructure, policies, or catalogs. Covers safety, boundaries, testing, docs-first, and docs-after."
applyTo: "src/**,tests/**,scripts/**,console/**,cli/**,infra/**,rule-catalog/**,policies/**"
---

# Coding Conventions

These rules are normative. Use RFC 2119 keywords: **MUST** / **MUST NOT** are hard gates
enforced in CI; **SHOULD** is a strong default that requires a written justification in the
PR description to deviate; **MAY** is optional. A PR that violates a MUST is not mergeable.

See sibling docs for the concepts referenced here:
[architecture.instructions.md](architecture.instructions.md) (tiers, quality gate, safety
invariants), [generic-scope.instructions.md](generic-scope.instructions.md) (customer-agnostic
scope), [app-shape.instructions.md](app-shape.instructions.md) (topology), and
[language.instructions.md](language.instructions.md) (language policy).

## Documentation Workflow

The design docs are the single source of truth; code and docs MUST stay in sync.

- **Docs-first (MUST)**: before writing or changing code, read the relevant design docs - the
  applicable `*.instructions.md` files and the [docs/roadmap/](../../docs/roadmap/README.md)
  documents for the area you are touching (e.g. project structure, the relevant phase,
  rule-catalog collection/governance, security). Code that contradicts the documented design is
  a defect. If the design itself is wrong, change the doc first - or in the same PR, with
  justification - before or alongside the code.
- **Docs-after (MUST)**: after changing code, update the affected documentation in the **same
  PR** so docs never drift from the implementation. Any change to behavior, structure, a public
  interface, a DI seam, a config key, or a schema MUST update the corresponding doc. Reviewers
  block a merge that leaves docs stale.
- **Bilingual docs (MUST)**: user-facing docs (root `README.md` and everything under
  `docs/**/*.md`) ship as `foo.md` (English canonical) + `foo-ko.md` (Korean translation)
  pairs. **Any edit to `foo.md` MUST update `foo-ko.md` in the same PR**, and vice versa.
  Adding a new user-facing doc MUST add both files. The `scripts/quality/localization/check-translations.sh`
  CI gate blocks merges where a `-ko.md` is missing or its recorded
  `translation_source_sha` does not match `git hash-object foo.md`. `.github/**` stays
  English canonical (no `-ko.md` pair). Full rules:
  [language.instructions.md](language.instructions.md#user-facing-doc-translations-ko).
- New modules, interfaces, injectable seams, config keys, and rule/schema changes are reflected
  in [docs/roadmap/](../../docs/roadmap/README.md) and the relevant instruction files.

## General

- **Bilingual (English + Korean) everywhere**: Korean is allowed in comments,
  docstrings, string values, logs, and tests. Only identifiers / filenames /
  branch names stay ASCII, and machine records (audit / events / log keys /
  config keys) SHOULD stay English for replay and correlation - see
  [language.instructions.md](language.instructions.md).
- **Single Responsibility Principle (MUST)**: every module, class, and function MUST have
  exactly one reason to change - one clearly stated responsibility. A unit that mixes
  unrelated concerns (e.g. routing + policy evaluation + I/O, or decision + execution +
  audit) MUST be split. A PR that introduces or worsens a multi-responsibility unit is not
  mergeable; extract the extra concerns behind their own interfaces or modules.
- Keep modules small and single-purpose; the core engine MUST stay UI-agnostic and portable.
  Prefer files under ~400 lines and functions with a single clear responsibility. Three
  CI-enforced structural gates back this rule:
  [scripts/quality/architecture/check-file-loc.sh](../../scripts/quality/architecture/check-file-loc.sh) (warn > 400 LOC, fail > 800
  in enforce mode),
  [scripts/quality/architecture/check-agents-imports.sh](../../scripts/quality/architecture/check-agents-imports.sh) (mirror of the
  `core/` boundary applied to `agents/`), and
  [scripts/quality/architecture/check-subsystem-fanout.sh](../../scripts/quality/architecture/check-subsystem-fanout.sh)
  (warn >= 8 sibling `core.*` subsystems imported by one file, fail >= 15 in enforce mode).
  All three ship warn-only; each G-series refactor tracked in issue #14 flips its target
  file's threshold to `enforce`.
- Favor CSP-neutral abstractions (OPA for policy, Terraform for IaC) over vendor-specific APIs.
  Vendor SDK calls MUST sit behind a provider interface. **Azure is the only implemented
  target** (see [Implementation Focus](../copilot-instructions.md#implementation-focus-must));
  the interface is preserved so a future non-Azure adapter is additive, but no other adapter
  is built until it is scoped in a future phase.
- Make behavior configuration-driven; do not bury environment specifics in code. Configuration
  MUST be validated against a schema at startup and the process MUST fail fast on invalid config.
- **Capability flags MUST separate `available`, `enabled`, and authority / `mode`.** Availability covers
  prerequisites and terms; enabled is preference; authority controls observe / simulate / execute.
- A complete user-facing capability SHOULD start enabled once available and MUST expose Settings
  state, prerequisites, and an unavailable reason. Authorized changes use concurrency plus audit
  without redeploy; env / IaC is a ceiling, not the only control. Hidden env-only flags are incomplete.
- External-transfer or billed tools, secret-backed channels, privileged mutations, previews, and test
  fakes stay unavailable until gated; then default enabled unless the owning design records why not.
- Enabling MUST NOT raise autonomy: shadow promotion, RBAC, risk, approval, verification, rollback,
  and kill switches stay authoritative. Flag tests MUST cover defaults, Settings authorization,
  persistence / audit, unavailable degradation, and shadow / enforce independence.
- Use distinct local variable names for unrelated types in separate branches. Strict mypy fixes
  the inferred type from the first assignment, so reusing one name for different page, result, or
  record types creates avoidable type-check failures.
- Customer-specific behavior MUST be supplied by **dependency injection** - a fork registers its
  implementations at the composition root and selects bindings via config; it MUST NOT edit
  `core/`. See the injectable seams in
  [project-structure.md](../../docs/roadmap/architecture/project-structure.md#customization-via-dependency-injection).
- Use the shared tier vocabulary in code and identifiers: `T0`, `T1`, `T2`, `trust-router`,
  `deterministic-engine`, `rule-catalog`, `risk-gate`, `remediation-pr`, `shadow-mode`, `hil`.

## Error Handling and Boundaries

- Validate untrusted input at system boundaries only (event ingress, API, config, rule-catalog
  load); do not add defensive checks for states the type system already makes impossible.
- Fail closed: on ambiguity, verification failure, or an unexpected error in an action path,
  abstain or escalate to `hil` rather than executing. Never fail open into an autonomous change.
- Do not swallow errors. Propagate with context, or handle explicitly; empty catch blocks and
  bare excepts are prohibited. Errors that abort an action MUST produce an audit-log entry.
- Error messages and exceptions MUST be English, actionable, and free of secrets or
  customer-identifying values.

## Safety

- Never hardcode secrets, connection strings, subscription IDs, tenant IDs, resource names,
  endpoints, or customer names. Load them from environment or a secret store at runtime.
  Secret scanning (e.g. gitleaks) runs in CI and a positive finding blocks the merge.
- **Deployment resource names** follow the CAF naming convention documented in
  [../../docs/roadmap/deployment/deploy-and-onboard.md § Resource Naming Convention](../../docs/roadmap/deployment/deploy-and-onboard.md#resource-naming-convention).
  The name is decided in Terraform (`infra/`) at plan time; Python code reads it from an env
  var. Never compute a resource name in Python and never bake env/region into a Python
  literal.
- **Resource-type swaps** stay portable via the infra-module boundary in
  [../../docs/roadmap/architecture/csp-neutrality.md § Approved Alternative Azure Implementations](../../docs/roadmap/architecture/csp-neutrality.md#approved-alternative-azure-implementations).
  A swap picks a different sub-module under `infra/modules/<seam>/`; the module's output
  contract stays fixed so callers do not branch on the alternate.
- **Provider Protocols are async by default.** The five I/O-bound seams (`EventBus`,
  `StateStore`, `SecretProvider`, `WorkloadIdentity`, `Inventory`) MUST be declared `async` -
  real backends (Kafka, asyncpg, Key Vault, OIDC exchange, Azure Resource Graph queries)
  block the event loop otherwise. The three CPU / startup-only seams (`SchemaRegistry`,
  `ContractValidator`, `ConfigProvider`) stay sync. Tests rely on `pytest-asyncio` with
  `asyncio_mode = "auto"` (see
  [../../pyproject.toml](../../pyproject.toml)); no per-test marker required.
- Secrets MUST NOT be written to logs, audit entries, error messages, test fixtures, or
  committed config. Access secrets through an injected provider, never a global read at import.
- Keep the repo customer-agnostic; customer-specific values and logic belong in a fork
  (see [generic-scope.instructions.md](generic-scope.instructions.md)).
- Every autonomous action path MUST implement all four safety invariants: a stop-condition,
  a rollback path, a blast-radius limit, and an audit-log write. Code that executes changes
  without all four is incomplete and MUST NOT merge.
- **ActionType schema is the enforcement surface for those invariants.** New ontology
  `ActionType` declarations MUST supply `rollback_contract` from the enum
  (`pr_revert` / `scripted` / `pitr` / `snapshot_restore` / `state_forward_only`) - the
  legacy `none` value is gone. A genuinely one-way mutation sets `irreversible: true` and
  is routed HIL+quorum by the risk-gate; it never uses `rollback_contract` to silence the
  invariant. Preconditions and stop_conditions belong on the ActionType, not the executor.
- Autonomous actions MUST be idempotent: re-delivery of the same event or a retried action
  MUST NOT cause duplicate changes. Use a stable idempotency key and deduplicate on it.
- Default new actions to **shadow mode** (judge and log only) - every upstream ActionType
  declares `default_mode: shadow` and a measurable `promotion_gate`. Promotion to enforce
  is an explicit, separately reviewed change, never bundled with the capability's first PR,
  and MUST measure the promotion_gate on the frozen scenario set before merging.
- The audit log is append-only and MUST record, per action: event id, tier, decision,
  idempotency key, actor identity, timestamp, shadow-vs-enforce mode, and rollback reference.

## Logging and Observability

- Emit structured logs (key-value / JSON), not free-form strings. Every log line for an action
  MUST carry a correlation/event id so a decision can be traced end to end.
- Use consistent levels: `error` (action failed or safety abort), `warn` (degraded/escalated),
  `info` (lifecycle and decisions), `debug` (diagnostic). Do not log secrets or customer values.
- Instrument the control loop with metrics for the KPIs that matter: per-tier volume, LLM
  escalation rate, auto-vs-`hil` ratio, action success/rollback counts, and shadow-mode outcomes.

## Determinism and LLM Use

- Prefer a deterministic rule for any repeatable decision. Reach for an LLM only after the
  T0/T1 tiers cannot resolve the case; target keeping LLM inference at ~5-10% of events.
- LLM (T2) output MUST pass the quality gate before it can execute: mixed-model cross-check,
  a verifier that re-validates the proposed action against policy-as-code and what-if, and
  grounding with rule/policy citations. Execution eligibility is granted by deterministic
  verification, never by the model alone; abstain when unsupported.
- LLM prompts, model IDs, and thresholds are configuration, not hardcoded literals, so they can
  be versioned and swapped without code changes.

## Dependencies and Versioning

- Pin dependencies with a lockfile; CI installs from the lockfile only. Do not float versions.
- New third-party dependencies require justification in the PR and MUST have a compatible OSS
  license; prefer OSS and CSP-neutral libraries over vendor lock-in.
- Keep dependencies current via reviewed, isolated bump PRs; a scheduled vulnerability scan
  (e.g. dependency audit) runs in CI and high-severity findings block the merge.

## Testing

- **Edit loop**: run the smallest executable test that can falsify the current change. Do not run a
  package, subsystem, or repository suite when one test file or node id is sufficient.
- **Completed batch**: run the route-selected focused checks, then `make test-changed` for
  working-tree changes or `make test-changed DIFF=<base>...HEAD` for a branch, plus
  `bash scripts/verify.sh --fast`. The selector includes untracked files and uses conservative
  whole-suite fallbacks for global Python test configuration.
- **Focused pytest facade**: use `bash scripts/verify.sh --full <path>` when the completed slice
  needs pytest through the common gate runner. A path is mandatory; pathless `--full` is rejected.
- **Whole-repository suite**: `bash scripts/verify.sh --all` is reserved for an explicit user
  request, a merge/release boundary, or a changed-test selector full fallback. It MUST NOT run after
  every edit, hardening batch, commit, or push. A green whole-suite result applies to that exact
  commit and environment and MUST NOT be repeated while relevant inputs are unchanged; use CI as
  the authoritative merge/release regression gate when available.
- Diff-scoped testing is a development feedback optimization, not proof of complete regression or
  coverage. It MUST NOT replace relevant safety property tests, focused slice verification, or the
  authoritative full coverage/regression gates at merge and release boundaries.
- Cover the `deterministic-engine` and `risk-gate` with unit tests; these are the safety core
  and MUST hold a high coverage bar (target ≥ 90% line/branch, enforced as a CI gate).
- Use fixtures for rule-catalog entries and event payloads; keep them English and secret-free.
  Fixtures follow the normalized rule schema (`id, source, severity, category, resource-type,
  check-logic, remediation`) so they exercise real shapes.
- Add a regression test with every rule change and every fixed defect; the continuous update
  pipeline (source watcher → shadow evaluation → regression → promote/rollback) depends on them.
- Use property-based tests for the risk gate and idempotency: assert invariants such as
  "high-risk never auto-executes", "shadow mode never mutates", and "re-applying an action is
  a no-op" across generated inputs.
- Every autonomous action path MUST have a shadow-mode test proving it judges and logs without
  mutating, plus a rollback test proving the rollback path restores prior state.
- Do not weaken, mock away, or skip safety checks to make tests pass. Tests MUST be
  deterministic (seed randomness, no reliance on wall-clock or live network).

## Commits and PRs

- Small, focused commits with clear English messages describing intent. Use Conventional
  Commits (`type(scope): summary`, e.g. `feat(risk-gate): ...`, `fix(rule-catalog): ...`).
- Actions taken by the control plane are delivered as remediation PRs, not out-of-band edits.
- A PR MUST state the change intent, its safety mode (shadow vs enforce), and how the safety
  invariants and tests are satisfied. PRs MUST NOT introduce customer-identifying values.

## Formatting

- Code and Markdown MUST pass the repo formatter and linter in CI before review; formatting is
  not a review discussion. Wrap prose and comments at a consistent width and end files with a
  single trailing newline.
