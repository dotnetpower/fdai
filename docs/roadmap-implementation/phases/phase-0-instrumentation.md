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
| Phase 0 work items W1-W6 | in-progress | Work-item deliverables and acceptance checks in this document; current source and test paths named by each work item | This ledger adoption does not infer completion from repository shape. Each work item remains bounded by its own acceptance check and the exit criteria below. |
| Sequenced task timeline | implemented | `docs/diagrams/fdai-roadmap-phases-phase-0-instrumentation-01.diagram.yaml`; `npm --prefix tools/architecture-diagrams run check` | The maintained bilingual FDAI diagram replaces the former Mermaid rendering without changing task dependencies or implementation authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-20 | in-progress | Adopted the implementation ledger; earlier work-item provenance was not reconstructed. Replaced the task timeline with a repository-owned bilingual diagram. | `current change`; Phase 0 roadmap pair, diagram specification, and focused diagram checks. | Review each W1-W6 acceptance check against current implementation and CI evidence before raising any scope row to implemented or validated. |

### Remaining work

- [ ] Classify every W1-W6 work item against its declared acceptance check, cite the current source and CI evidence, and split the aggregate scope row when independently provable states differ.
