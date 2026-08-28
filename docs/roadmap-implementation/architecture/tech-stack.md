# Technology Stack implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Python service distributions and five-service runtime | validated | `services/`; `packages/service-contracts/`; `config/independent-service-live-evidence-manifest.json`; `config/independent-service-remote-evidence.attestation.jsonl` | The five service distributions, images, health boundaries, and protected N/N-1/N transitions have retained remote evidence. |
| Terraform Azure platform, Event Hubs Kafka, and PostgreSQL plus pgvector | implemented | `infra/`; `alembic/`; `service-migrations/branches/`; focused infrastructure and migration tests | The stack and protected deployment mechanics exist. The general platform owner still requires a retained governed apply receipt before it can claim validation. |
| OPA/Rego policy and catalog execution | implemented | `policies/`; `rule-catalog/`; `scripts/catalog/sync-rule-semantics.py`; the `rule-semantics` gate in `scripts/verify.sh` and `.github/workflows/ci.yml`; `tests/integration/scripts/test_sync_rule_semantics.py`; focused policy and catalog tests | Shipped Rego, normalized catalog metadata, OPA compilation, and deterministic evaluation are executable. Rule-to-policy semantic drift is also enforced: the scoped gate fails the change when a rule diverges from its policy, and it fails rather than skips when OPA is unavailable. |
| OpenTelemetry and Azure observation adapters | in-progress | `shared/telemetry/`; `delivery/azure/metric_logs.py`; `delivery/azure/log_query.py`; `delivery/azure/telemetry_query.py`; observation campaign tests | Instrumentation and bounded Azure adapters are implemented. One retained end-to-end operational telemetry campaign across all five services remains open. |
| Weekly model lifecycle reconciler | in-progress | `.github/workflows/model-lifecycle-reconcile.yml`; `scripts/deployment/azure/model_lifecycle_reconciler.py`; `uv run pytest -q --no-cov tests/integration/scripts/test_model_resolution_lifecycle.py` passed 22 cases | The proposal-only path is bounded, deterministic, and deduplicated while a matching draft is open; it cannot activate or deploy a model. Expired-proposal runtime holds, closed-or-merged retry handling, and a governed scheduled-run receipt remain open. |
| Non-Azure managed alternatives | deferred | [OD-3](../../roadmap/architecture/tech-stack.md#od-3-multi-cloud-event-bus-phase-4--tbd); [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must) | Alternatives remain design options, not implemented or parity-validated targets. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Corrected the weekly model reconciler item from not implemented to its proven proposal-only state and separated its missing expiry-to-hold and governed-run evidence from platform apply and five-service telemetry evidence. Non-Azure alternatives remain an explicit deferred decision rather than open implementation work. | `current change`; model lifecycle reconciler source and protected workflow; focused lifecycle tests passed 22 cases; Issues #356-#358 and #351. | Complete the three governed evidence and expiry-hold issues below. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and aligned the stack with the current five-service, Rego, telemetry, and Azure-only implementation. | `current change`; service evidence, infrastructure, policy, telemetry, and focused test paths cited above. | Retain platform apply and telemetry campaign evidence; keep non-Azure targets deferred. |
| 2026-08-15 | implemented | Promoted the rule-to-policy semantic drift check from an on-demand command to an enforced gate in `verify.sh` and CI, and corrected the evidence wording that treated executability as enforcement. | `current change`; `scripts/verify.sh`; `.github/workflows/ci.yml`; `tests/integration/scripts/test_sync_rule_semantics.py`; `uv run python scripts/catalog/sync-rule-semantics.py --check` exits 0 on the shipped catalog; the focused synchronizer suite passes. | Platform apply and telemetry campaign evidence remain open. |

### Remaining work

- [ ] Retain a governed platform apply receipt binding the exact Terraform plan, source revision, service images, migrations, identities, and post-apply health under [issue #358](https://github.com/dotnetpower/fdai/issues/358).
- [ ] Retain one end-to-end OpenTelemetry and Azure query campaign across all five services with correlation, retention, failure, and unavailable-state evidence under [issue #357](https://github.com/dotnetpower/fdai/issues/357).
- [ ] Under [issue #356](https://github.com/dotnetpower/fdai/issues/356), prove an expired unmerged proposal creates a typed human-review hold against the authoritative source digest without changing deployment state, handle closed-or-merged retries deterministically, and retain one governed weekly run receipt; keep every replacement draft-PR plus shadow-replay gated.
- [x] Keep non-Azure alternatives deferred under [issue #351](https://github.com/dotnetpower/fdai/issues/351) until one target is explicitly approved with parity and rollback evidence.
