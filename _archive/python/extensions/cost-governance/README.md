# FDAI Cost Governance

`fdai-cost-governance` is an optional FDAI distribution for reviewed Cost Governance candidate
resources. It packages rules, policies, fix (`remediation`) templates, a workflow, and the exact semantic
profile without adding an agent or granting approval, execution, or promotion authority.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_cost_governance/` | Typed facade, deterministic advisory model, and bounded jobs |
| `src/fdai_cost_governance/resources/manifest.json` | Canonical SHA-256 resource inventory |
| `src/fdai_cost_governance/resources/rules/` | Inert rule candidates with stable ids |
| `src/fdai_cost_governance/resources/policies/` | Policy candidates referenced by rules |
| `src/fdai_cost_governance/resources/remediation/` | Fix templates referenced by rules |
| `src/fdai_cost_governance/resources/workflows/` | Observation-mode workflow candidates |

## Activation boundary

You can use `build_cost_governance_bundle()` in a reviewed image composition root. Pass the
returned generic `VerticalPackageBundle` to Core with the exact wheel digest and required provider
bindings. Installation starts disabled, and unavailable host, ontology, or provider requirements
remain explicit diagnostics.

Enabling the package registers only validated candidate assets. Every workflow remains in
observation mode, where FDAI evaluates and records but does not apply changes. Promotion, human
approval, execution, effect verification, and audit closure remain in their existing Core
authority boundaries.

## Collection and analysis

The package provides `fdai-cost-collector` and `fdai-cost-analyzer` job entrypoints. Both read the
authoritative package-activation revision before work. The collector uses an injected read-only
Azure Cost Management FOCUS transport and credential, then appends immutable observations with a
CAS cursor. The analyzer publishes evidence-quality-checked samples through the event bus for
Huginn normalization. Njord remains the sole `CostAnomaly` and `Budget` publisher.

The jobs are absent by default in infrastructure. When scheduled, they use the read-only inventory
identity, not the `identity/finops` execution identity. A disabled or release-mismatched package
makes no provider call and publishes no sample.

## Validation mechanics

`CostObservationCampaignReducer` accounts for every campaign outcome and effect-settlement status
without counting excluded, censored, unscorable, or estimated-only evidence as success.
`CostPromotionReadinessGate` evaluates the exact source, wheel, image, asset manifest, semantic
profile, ontology release, runtime configuration, and activation revision. Package activation,
ActionType, and Workflow targets receive separate review-only results.

Synthetic, fixture, and unit evidence can test these mechanics but always blocks operational
readiness. Only live authoritative evidence can reach `ready-for-independent-review`, which still
does not approve, enable, execute, or promote anything.

## Verification

Run focused package checks from the repository root:

```bash
uv run ruff check extensions/cost-governance/src extensions/cost-governance/tests
uv run mypy --strict extensions/cost-governance/src/fdai_cost_governance
uv run pytest -q --no-cov extensions/cost-governance/tests
uv build --package fdai-cost-governance
```
