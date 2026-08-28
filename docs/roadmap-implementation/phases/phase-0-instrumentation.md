# Phase 0 - Instrumentation and Unblocking implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Migrated implementation notes

> **Implementation status**: Telemetry, configuration, and event contracts; PostgreSQL
> migrations; the frozen `v2026.07` scenarios; `tools/reference_agent/`;
> `tools/baseline_run.py`; baseline reports; provider fakes; the pgvector/Redpanda local preset;
> and the exemption schema and template are implemented. Entra app/group provisioning, PR-trailer
> no-self-approval CI, the exemption auto-expiry/digest job, and production validation of all P0
> exit evidence are incomplete. The task tables preserve the original plan and acceptance criteria;
> this callout describes the current repository state.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| W1 persistence, required CI, and golden telemetry | in-progress | `alembic/versions/20260705_0001_base.py`; `.github/workflows/ci.yml`; `services/core-control-plane/tests/persistence/test_migrations_integration.py`; `services/core-control-plane/tests/telemetry/test_golden_fixture.py` | The base migration, required merge gate, and deterministic golden metrics fixture exist. This classification change did not rerun the database integration or retain applied-environment and live telemetry evidence. |
| W1 service boundaries, contracts, config, telemetry, cache, and dashboard | in-progress | `pyproject.toml`; `services/core-control-plane/src/fdai/shared/contracts/`; `services/core-control-plane/tests/contracts/`; `services/core-control-plane/src/fdai/shared/config/`; `services/core-control-plane/src/fdai/shared/telemetry/`; `alembic/versions/20260705_0002_layered_cache.py`; `docs/dashboards/phase-0-kpi.json`; `.github/workflows/ci.yml` | Local implementations and required-CI independent-service enforcement exist. File-backed config, contract generation and compatibility enforcement, end-to-end correlation tracing, cache rotation and latency evidence, and non-deferred dashboard panels remain incomplete. |
| W2 frozen scenario assets and replay | in-progress | `services/core-control-plane/tests/scenarios/schema.json`; `services/core-control-plane/tests/scenarios/test_frozen.py`; `services/core-control-plane/tests/scenarios/test_v2026_07_replay.py`; `services/core-control-plane/tests/scenarios/manifests/v2026.07.json`; `.github/workflows/ci.yml` | Schema, balance, synthetic-scope, replay, service-owned immutable-directory protection, and bilingual natural-language checks exist. Scrub coverage remains UUID-focused and capability-pack coverage remains incomplete. |
| W3 synthetic baseline mechanics | in-progress | `tools/reference_agent/`; `tools/baseline_run.py`; `docs/baselines/v2026.07.json`; `docs/baselines/v2026.07.md`; `services/core-control-plane/tests/tools/test_baseline_runner.py` | Deterministic tooling and committed synthetic artifacts exist. The current report does not satisfy every W3 artifact acceptance condition and explicitly remains `synthetic-harness`, incomplete, and not claim eligible. |
| W4 Azure infrastructure and identity blocker | in-progress | `infra/main.tf`; `infra/modules/operator-api/container-app/`; `infra/tests/`; `docs/runbooks/entra-app-registration.md`; `services/operator-service/tests/test_operator_iam_family.py` | Infrastructure and identity configuration surfaces exist. Deny-by-default Azure Policy, the least-privilege probe, approval-bot registration, complete group and Conditional Access bindings, recertification, and governed tenant evidence remain incomplete. |
| W5 exemption lifecycle | in-progress | `services/core-control-plane/src/fdai/rule_catalog/schema/exemption.schema.json`; `services/core-control-plane/src/fdai/rule_catalog/schema/exemption_cli.py`; `services/core-control-plane/tests/exemption/`; `services/core-control-plane/tests/rbac/test_no_self_approval.py`; `scripts/governance/exemption-expire.py`; `docs/runbooks/exemption-workflow.md` | Schema, runtime separation, and owner/SLA documentation exist. The exact PR-trailer identity flow, scheduled expiry with audit and assignment re-apply, and expiry digest are incomplete. |
| W6 provider contracts and local stack | in-progress | `services/core-control-plane/src/fdai/shared/providers/`; `services/core-control-plane/tests/providers/test_contracts.py`; `infra/local/docker-compose.yml`; `scripts/deployment/local/dev-up.sh`; `scripts/deployment/local/dev-down.sh` | Provider protocols, fakes, and Compose services exist. The shared contract matrix does not yet register PostgreSQL and Redpanda, and executable pgvector, Kafka round-trip, and no-cloud-call checks are incomplete. |
| Sequenced task timeline | implemented | `docs/diagrams/fdai-roadmap-phases-phase-0-instrumentation-01.diagram.yaml`; `npm --prefix tools/architecture-diagrams run check` | The maintained bilingual FDAI diagram replaces the former Mermaid rendering without changing task dependencies or implementation authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | implemented | Added the independent-service ownership and dependency-direction checker to the required lint job and pinned that wiring with a CI-contract regression. | `current change`; `uv run python scripts/quality/architecture/check-independent-services.py`; focused CI-contract test. | Complete the remaining W1 config, contract, correlation, cache, and dashboard exits below. |
| 2026-08-29 | in-progress | Corrected the frozen-scenario CI path to the service-owned version directory. Existing version directories now reject additions, edits, deletes, renames, symlinks, and other type changes while a new version directory remains additive. Replaced the English-only prose rejection with field-aware checks that pass Korean natural-language payloads through the Event contract while rejecting non-ASCII scenario ids, source ids, rule ids, resource refs, paths, and nested machine values. | `current change`; focused scenario tests and CI-contract regression; CI contract, language, and roadmap checks. | Expand synthetic-data scrubbing beyond UUIDs and complete all six dimensions in every capability pack. |
| 2026-08-29 | in-progress | Audited W1-W6 against current source, tests, CI, and runtime evidence, then replaced the aggregate scope row with bounded areas. The audit keeps every area `in-progress` until its cited acceptance checks are rerun or the required runtime evidence exists, and keeps synthetic mechanics separate from live validation. | `current change`; `docs/roadmap/phases/phase-0-instrumentation.md`; exact source and test paths in the scope table; repository and CI wiring review only. | Complete the observable exits below. Live Azure, IdP, and non-synthetic baseline evidence require separately authorized operations. |
| 2026-08-20 | in-progress | Adopted the implementation ledger; earlier work-item provenance was not reconstructed. Replaced the task timeline with a repository-owned bilingual diagram. | `current change`; Phase 0 roadmap pair, diagram specification, and focused diagram checks. | Review each W1-W6 acceptance check against current implementation and CI evidence before raising any scope row to implemented or validated. |

### Remaining work

- [x] Classify every W1-W6 work item against its declared acceptance check and split independently provable scope.
- [x] Add `check-independent-services.py` to required CI and pin the lint-job wiring with a focused CI-contract regression.
- [ ] Add a file-backed config provider, then record passing contract schema and compatibility tests, one ingest-to-audit correlation test, cache rotation and latency tests, and `test_dashboard_descriptor.py` with no deferred required panels.
- [x] Correct the frozen-scenario immutability path, including type changes, and prove `test_frozen.py` accepts English and Korean natural-language values while rejecting non-ASCII machine identifiers and paths.
- [ ] Add tenant, subscription, resource, endpoint, email, and secret scrub cases to `test_frozen.py`, and complete all six dimensions in every capability pack tracked by [issue #76](https://github.com/dotnetpower/fdai/issues/76).
- [ ] Retain one non-synthetic reference baseline and FDAI treatment on the identical frozen scenario set with complete metrics, minimum sample size, confidence intervals, and `claim_eligible=true`.
- [ ] Implement deny-by-default Azure Policy and its least-privilege probe; complete the approval-bot, group, Conditional Access, and recertification configuration; then retain governed tenant evidence.
- [ ] Replace the exemption expiry stub with a scheduled, audited assignment re-apply path and add the 14-day digest plus exact requester-versus-approver identity checks.
- [ ] Register PostgreSQL and Redpanda in the shared provider contract matrix and record passing pgvector-extension, Kafka round-trip, health, and no-cloud-call checks against the local Compose preset.
