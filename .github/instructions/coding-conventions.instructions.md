---
description: Coding conventions, safety rules, and testing expectations.
applyTo: "**"
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

- **Docs-first (MUST)**: before writing or changing code, read the relevant design docs — the
  applicable `*.instructions.md` files and the [docs/roadmap/](../../docs/roadmap/README.md)
  documents for the area you are touching (e.g. project structure, the relevant phase,
  rule-catalog collection/governance, security). Code that contradicts the documented design is
  a defect. If the design itself is wrong, change the doc first — or in the same PR, with
  justification — before or alongside the code.
- **Docs-after (MUST)**: after changing code, update the affected documentation in the **same
  PR** so docs never drift from the implementation. Any change to behavior, structure, a public
  interface, a DI seam, a config key, or a schema MUST update the corresponding doc. Reviewers
  block a merge that leaves docs stale.
- **Bilingual docs (MUST)**: user-facing docs (root `README.md` and everything under
  `docs/**/*.md`) ship as `foo.md` (English canonical) + `foo-ko.md` (Korean translation)
  pairs. **Any edit to `foo.md` MUST update `foo-ko.md` in the same PR**, and vice versa.
  Adding a new user-facing doc MUST add both files. The `scripts/check-translations.sh`
  CI gate blocks merges where a `-ko.md` is missing or its recorded
  `translation_source_sha` does not match `git hash-object foo.md`. `.github/**` stays
  English-only (no translation). Full rules:
  [language.instructions.md](language.instructions.md#user-facing-doc-translations-ko).
- New modules, interfaces, injectable seams, config keys, and rule/schema changes are reflected
  in [docs/roadmap/](../../docs/roadmap/README.md) and the relevant instruction files.

## General

- **English only** for all artifacts (see [language.instructions.md](language.instructions.md)).
- **Single Responsibility Principle (MUST)**: every module, class, and function MUST have
  exactly one reason to change — one clearly stated responsibility. A unit that mixes
  unrelated concerns (e.g. routing + policy evaluation + I/O, or decision + execution +
  audit) MUST be split. A PR that introduces or worsens a multi-responsibility unit is not
  mergeable; extract the extra concerns behind their own interfaces or modules.
- Keep modules small and single-purpose; the core engine MUST stay UI-agnostic and portable.
  Prefer files under ~400 lines and functions with a single clear responsibility.
- Favor CSP-neutral abstractions (OPA for policy, Terraform for IaC) over vendor-specific APIs.
  Vendor SDK calls MUST sit behind a provider interface. **Azure is the only implemented
  target** (see [Implementation Focus](../copilot-instructions.md#implementation-focus-must));
  the interface is preserved so a future non-Azure adapter is additive, but no other adapter
  is built until it is scoped in a future phase.
- Make behavior configuration-driven; do not bury environment specifics in code. Configuration
  MUST be validated against a schema at startup and the process MUST fail fast on invalid config.
- Customer-specific behavior MUST be supplied by **dependency injection** — a fork registers its
  implementations at the composition root and selects bindings via config; it MUST NOT edit
  `core/`. See the injectable seams in
  [project-structure.md](../../docs/roadmap/project-structure.md#customization-via-dependency-injection).
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
- Secrets MUST NOT be written to logs, audit entries, error messages, test fixtures, or
  committed config. Access secrets through an injected provider, never a global read at import.
- Keep the repo customer-agnostic; customer-specific values and logic belong in a fork
  (see [generic-scope.instructions.md](generic-scope.instructions.md)).
- Every autonomous action path MUST implement all four safety invariants: a stop-condition,
  a rollback path, a blast-radius limit, and an audit-log write. Code that executes changes
  without all four is incomplete and MUST NOT merge.
- Autonomous actions MUST be idempotent: re-delivery of the same event or a retried action
  MUST NOT cause duplicate changes. Use a stable idempotency key and deduplicate on it.
- Default new actions to **shadow mode** (judge and log only). Promotion to enforce is an
  explicit, separately reviewed change, never bundled with the capability's first PR.
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
  T0/T1 tiers cannot resolve the case; target keeping LLM inference at ~5–10% of events.
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
