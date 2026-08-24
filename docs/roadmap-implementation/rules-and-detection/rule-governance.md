# Rule Governance implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: Effect/scope/assignment/rule-set domain models, strict YAML loaders,
> the directory catalog loader, effect/enforcement transition CI, and T0 runtime assignment
> consumption are implemented. Startup loads one immutable governance catalog, and T0 applies
> resolved scope, exclusions, selectors, effect, enforcement, parameters, and precedence before
> ordinary authorization and safety checks. The catalog now loads strict Azure-shaped exemptions
> and binds them to the safety check. Maximum duration, scheduled expiry, ahead-of-expiry
> notifications, and lifecycle audit delivery remain open. Override resolution remains target
> design. Pull-request identity checks are implemented; trusted-verifier deployment remains
> external work.

> **Implementation status**: the effect foundation ships in
> [`rule_catalog/schema/effect.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/effect.py) - the
> `Effect` (`disabled` / `audit` / `deny` / `remediate`) and `Enforcement`
> (`enforce` / `do-not-enforce`) enums, the strictest-effect precedence
> (`deny` > `remediate` > `audit` > `disabled`) used to resolve conflicting assignments, and
> `validate_effect_transition` enforcing the transition table above (a raise to an enforce effect
> requires the separate promotion approval). The scope selection layer ships alongside in
> [`rule_catalog/schema/scope.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/scope.py) - the
> `ScopeLevel` hierarchy, `ScopeSelector` (resource-type / tag / resource-id, AND-of-declared),
> exclusions, `Scope.covers`, and the `most_specific` precedence helper. The `Assignment` artifact
> and the `resolve_assignments` conflict resolver (strictest effect wins; the most-specific scope
> supplies parameters; a specificity tie flags HIL; losers recorded for audit) ship in
> [`rule_catalog/schema/assignment.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/assignment.py). The
> `RuleSet` (initiative) grouping - version-pinned members with per-rule `default_effect` and
> `assignment_from_rule_set` - ships in
> [`rule_catalog/schema/rule_set.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/rule_set.py). The
> governance model layer (effect / scope / assignment / rule-set) is complete in-memory. The
> assignment catalog-as-code loader also ships:
> [`assignment.schema.json`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/assignment.schema.json) +
> `load_assignment_from_mapping`
> ([`governance_loader.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_loader.py)), which
> validates a YAML assignment and builds the domain object, failing at the boundary with every
> schema issue. The rule-set loader (`rule_set.schema.json` + `load_rule_set_from_mapping`) ships
> in the same module. A directory loader
> ([`governance_catalog.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_catalog.py),
> `load_governance_catalog`) reads the whole catalog-as-code tree (`assignments/` + `rule-sets/`),
> aggregating every file's issues. An assignment binds either an explicit `target_rule_ids` list or
> a `rule_set` (by id): the loader resolves a rule-set reference against the loaded rule-sets and
> expands it via `assignment_from_rule_set` (carrying the set's per-rule `default_effect` as
> overrides), so "rule-set applied to a scope" works end-to-end; an unresolved reference fails at the
> load boundary. The CI transition gate core also ships:
> `validate_catalog_transition`
> ([`governance_transitions.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_transitions.py))
> compares a previous and current `GovernanceCatalog` and rejects any per-rule effective-effect
> transition outside the allowed table - a new assignment/rule is validated from the mandated
> `audit` default, and raising to an enforce effect (`deny` / `remediate`) needs the assignment id
> in `promotions_approved`. The **enforcement** `do-not-enforce` -> `enforce` activation - the go-live
> flip that takes an enforce-tier effect out of shadow - needs the same approval, so a two-step
> `deny(shadow)` then `deny(enforce)` cannot reach production unreviewed. A thin `git`-diff CI script
> ([`check-governance-transitions.py`](../../../scripts/governance/check-governance-transitions.py)) wraps the
> validator: it materializes the catalog at the base ref and the working tree and fails the build on
> a rejected transition. The gate governs **effect + enforcement** transitions; it does not flag a
> scope / blast-radius **widening** (a lower-specificity scope can be offset by a tighter `selector`, so a
> sound widening check needs coverage analysis, not a specificity heuristic) - that is a separate
> future check. Runtime startup now loads this catalog once, and T0 resolves each finding against
> the immutable assignment tuple. Audit/disabled and non-enforcing decisions remain
> observation-only; parameter ties require human review; remediate+enforce still passes through
> execution authorization and the unified safety check.
>
> The shipped catalog-as-code schema now matches the "YAML Shapes" section below: a shared
> `Provenance` value object ([`provenance.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/provenance.py)),
> the `kind` ([`governance_kind.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/governance_kind.py))
> discriminator plus an artifact `version`, the canonical `scope://`
> [`ScopeRef`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/scope.py) address and the include/exclude
> [`ScopeBinding`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/scope.py) form (unified behind the
> `ScopeMatcher` protocol), and per-rule `parameter_overrides` all ship. A rule-set is bound through
> `rule_set` (or an explicit `target_rule_ids` list) and scope narrowing uses the richer `selector`
> (`resource_types` / `tags` / `resource_ids`).

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Effect, scope, assignment, and rule-set contracts | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/effect.py`; `scope.py`; `assignment.py`; `rule_set.py`; focused schema tests | Strict models reject invalid scopes, references, effects, and rule-set expansion. |
| Governance catalog and transition CI | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/governance_catalog.py`; `governance_transitions.py`; `scripts/governance/check-governance-transitions.py`; `.github/workflows/ci.yml` | Directory loading and reviewed effect/enforcement transition checks are wired. |
| Exemptions and expiry | in-progress | `services/core-control-plane/src/fdai/rule_catalog/schema/exemption.py`; `governance_catalog.py`; `delivery/catalog_exemption.py`; `runtime/control_loop.py`; `scripts/governance/exemption-expire.py`; focused loader, registry, safety-check, and runtime tests | Startup loads immutable strict artifacts and the safety check consumes them. Scheduled execution, configured maximum duration, notifications, and lifecycle audit delivery remain open. |
| Override artifact and resolution | not-started | [Overrides](../../roadmap/rules-and-detection/rule-governance.md#overrides); current change source audit | No override-specific schema, directory loader, precedence resolver, or runtime consumer exists. |
| T0 assignment consumption | implemented | `services/core-control-plane/src/fdai/runtime/control_loop.py`; `services/core-control-plane/src/fdai/core/control_loop/_execution.py`; `services/core-control-plane/src/fdai/core/control_loop/_process.py`; focused governance and pipeline tests | One immutable startup catalog supplies scope, exclusions, selectors, effect, enforcement, parameters, and precedence. Enforcing remediation still passes through execution authorization and the unified safety check. |
| Governance pull-request identity checks | implemented | `services/core-control-plane/src/fdai/rule_catalog/schema/governance_review_authority.py`; `services/core-control-plane/src/fdai/delivery/gitops_pr/governance_review.py`; `scripts/governance/check-governance-review-authority.py`; `.github/workflows/ci.yml`; focused authority, metadata, CLI, and workflow tests | CI fetches exact-head GitHub commit, review, and Check Run facts and accepts identity evidence only from the configured trusted verifier App. Missing configuration or attestation blocks governed changes. Deploying that external Entra verifier and retaining blocked-then-cleared evidence remain operational work. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | implemented | Closed the stale detection-and-routing threshold residual against Constitution Article 4. Production T1, quality-gate, and self-consistency values already come from the versioned `config/1.0.0` schema; Heimdall repeat policy comes from bounded Runtime Settings. The remaining three Heimdall security-correlation literals now use bounded startup settings with unchanged defaults. An AST-derived test fixes the exact seven numeric LLM consumers and five Heimdall setting consumers, so a new unbound production threshold fails the gate. | [Issue #219](https://github.com/dotnetpower/fdai/issues/219); focused setting, runtime, framework-layout, ingress, and threshold checks pass 134 cases. | None for production-composed routing and detection threshold bounds. Pure detector constructor defaults remain injectable algorithm defaults, not active composition policy. |
| 2026-08-19 | implemented | Declared the last two unbound adaptive thresholds. `promotion_gate` in the shipped `ontology/action-type` contract now also declares `min_fidelity` and `max_recurrence_rate` as optional ratio bounds, documented as bound declarations that the ActionType promotion evaluator does not read, and `GraphModelPromotionPolicy` derives its accepted range from them instead of the literal `0.0 <= value <= 1.0` it restated. `UNBOUND_ADAPTIVE_THRESHOLDS` is now empty and the focused test asserts that every discovered numeric threshold is bound. Also corrected the frozen scenario count in `test_shadow_eval.py`, which `544e80a72` broke by adding three `sre.*` scenarios without updating it. | `current change`; `tests/core/operational_learning/test_threshold_bounds.py`, `tests/core/assurance_twin`, `tests/contracts`, `tests/rule_catalog`, and `tests/core/measurement` passed 1640 focused cases; task-scoped Ruff, format, and mypy passed; `check-core-imports` and `check-property-semantic-coverage` passed. | Extend the registry beyond the promotion gate to detection and routing thresholds; those are still literals at their use sites. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source, CI wiring, and focused tests listed in the scope table. | Wire T0 consumption, complete exemption operations, and implement governed overrides and PR identity checks. |
| 2026-08-17 | in-progress | Added the pure governance pull-request review-authority decision: operator object identity, the capability each change class requires, distinct-approver quorum, phishing-resistant high-risk approvals, revision-bound freshness, and author/co-author/committer self-approval prevention. | `current change`; `services/core-control-plane/src/fdai/rule_catalog/schema/governance_review_authority.py`; `PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/packages/service-contracts/src" .venv/bin/python -m pytest -q --no-cov services/core-control-plane/tests/rule_catalog/schema/test_governance_review_authority.py` passed 16 tests. | Bind the decision to real pull-request review metadata in the governance CI gate and retain one blocked-then-cleared evidence record. |
| 2026-08-17 | in-progress | Hardened the review-authority decision so a head commit time that is not absolute fails closed: freshness is never compared against an ambiguous instant and no approval counts toward the quorum. | `current change`; `PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/packages/service-contracts/src" .venv/bin/python -m pytest -q --no-cov services/core-control-plane/tests/rule_catalog/schema/test_governance_review_authority.py` passed 17 tests. | Bind the decision to real pull-request review metadata in the governance CI gate and retain one blocked-then-cleared evidence record. |
| 2026-08-18 | in-progress | Added `shared/ontology/threshold_bounds.py`, which reads the numeric promotion-gate bounds from the shipped `ontology/action-type` contract and offers one checker. `ShadowDwellThresholds` now derives its floors and its accuracy ceiling from that declaration instead of restating them, and one focused sweep proves every registered adaptive threshold stays inside its declared bound while the pydantic `PromotionGate` model and the JSON contract cannot drift apart. Two `GraphModelPromotionPolicy` rate thresholds have no ontology declaration and are named as an explicit gap rather than left silent. | `current change`; `tests/core/operational_learning` passed 88 focused cases; `tests/core/risk_gate`, `tests/core/measurement`, `tests/core/assurance_twin`, and `tests/rule_catalog` passed 1716 cases; task-scoped Ruff, format, and strict mypy passed. | Declare ontology bounds for `min_fidelity` and `max_recurrence_rate`, then move them out of the unbound set; extend the registry beyond the promotion gate to detection and routing thresholds. |

| 2026-08-23 | in-progress | Added a strict delivery boundary that joins GitHub review state, exact commit, and timestamp to deployment-verified Entra OID, FDAI roles, and phishing-resistant assurance. Latest decisive review state wins, stale revisions remain visible to the pure authority decision, and missing or early attestations fail closed. | `current change`; `delivery/gitops_pr/governance_review.py`; focused metadata and authority tests passed 23 cases. | Bind a deployment-owned identity/assurance provider and real pull-request metadata collector into CI, then retain a blocked-and-cleared evidence record. |
| 2026-08-23 | implemented | Connected the authority decision to GitHub's exact-head PR, commit, review, and Check Run metadata. A configured verifier App must publish the bounded Entra principal bundle in its successful exact-head Check Run; an absent App id, missing or failed check, stale revision, unverified role, weak assurance, self-approval, or insufficient quorum blocks CI. Assignment changes use the stricter enforce-promotion class until transition intent is independently proven. | `current change`; `scripts/governance/check-governance-review-authority.py`; `.github/workflows/ci.yml`; focused governance CLI, bridge, authority, and workflow tests passed 69 cases. | Deploy the trusted Entra verifier GitHub App and retain one blocked-then-cleared governed PR evidence record. |
| 2026-08-23 | in-progress | Completed immutable T0 assignment consumption and integrated strict exemption artifacts into the startup governance catalog and safety check. Hardened duplicate JSON detection, UTC and terminal-state validation, unknown-rule and duplicate-active-scope rejection, exact resource identity, canonical ARM scope parsing, subscription isolation, deterministic fallback, and terminal revocation across both registries. | `current change`; focused governance loader, exemption model/CLI, catalog and fallback registry, runtime composition, safety-check, and T0 pipeline checks passed. Twelve adversarial hardening rounds leave no Medium-or-higher implementation finding in this slice. | Configure maximum exemption duration and alert lead time, then wire scheduled expiry, notifications, and lifecycle audit delivery. Override delivery and trusted-verifier deployment remain separate. |

### Remaining work

- [x] Load one immutable governance catalog at startup and prove T0 applies resolved effect, enforcement, scope, exclusions, and precedence without bypassing the safety check. Focused pipeline coverage proves remediate+enforce still obeys the unified safety decision.
- [ ] Configure and enforce the maximum exemption duration and alert lead time, then schedule expiry and deliver ahead-of-expiry notifications with lifecycle audit evidence. Catalog loading and safety-check consumption are implemented.
- [ ] Implement the bounded override schema, loader, precedence resolver, and runtime consumption with resource-group-or-narrower scope checks.
- [x] The deterministic pull-request review-authority decision enforces operator identity, the required capability per change class, a distinct-approver quorum, phishing-resistant high-risk approvals, revision-bound approval freshness, and author/co-author/committer self-approval prevention, proven by `services/core-control-plane/tests/rule_catalog/schema/test_governance_review_authority.py`.
- [x] Bind the decision to exact-head pull-request, commit, review, and trusted verifier Check Run metadata in CI. Missing trusted attestation fails closed; focused CLI and workflow tests cover accepted, sub-quorum, self-approval, and untrusted-App cases.
- [ ] Deploy the trusted Entra verifier GitHub App, configure `FDAI_GOVERNANCE_IDENTITY_APP_ID`, and retain one evidence record showing a self-approval or sub-quorum change blocked and the corrected change cleared.
