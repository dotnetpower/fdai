# Capability bundle lifecycle implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Bundle validation and immutable runtime registration | implemented | `core/capability_catalog/`; `composition/install_capability_bundle`; focused capability catalog tests | Unknown targets, provider mismatches, duplicate ids, and dangling references block activation without changing the current runtime. |
| Durable trusted artifacts and skill disclosure | implemented | `core/supply_chain/`; `delivery/trust/`; PostgreSQL trusted-artifact adapters | Artifacts retain exact content, signature, publisher, state, and revision; runtime disclosure is rebuilt from reverified records. |
| Governed external skill source lifecycle | implemented | `core/skills/source_registry.py`; `core/supply_chain/skill_source_*.py`; skill source API routes | Installation starts disabled, revocation preserves provenance, and production reloads disclosure after a command. |
| Exact-artifact governed lifecycle evidence | in-progress | [Issue #355](https://github.com/dotnetpower/fdai/issues/355); `config/package-assurance.json` | Local mechanics and linked-receipt rules exist, but the protected receipt set covering install, enable, disable, revoke, restart, disclosure reload, typed action routing, and audit remains open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-04 | implemented | Migrated the inline owner status into this ledger with `--merge-existing`, merged the duplicate receipt-set item into the Issue #355 phrasing that also covers restart, and marked it deferred because Issue #355 closed as not planned. | `current change`; `scripts/automation/migrate-roadmap-implementation-ledgers.py --merge-existing --apply`; Issue #355 closure comment. | Schedule a new issue before retaining the linked exact-artifact receipt set. |
| 2026-09-27 | implemented | Returned lifecycle transition selection and completeness to this capability owner instead of the global package gate. | `current change`; minimum package assurance policy and this owning design. | Retain the governed operational linked receipt set under Issue #355. |
| 2026-09-26 | implemented | Allowed a complete lifecycle to use bounded linked receipts with one exact artifact lineage instead of requiring one monolithic live run. | `current change`; package assurance policy, checker, owner documentation, and focused policy tests. | Retain the governed operational linked receipt set under Issue #355. |
| 2026-08-21 | implemented | Moved the existing capability bundle and trusted-artifact lifecycle into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain governed operational evidence for a complete install, enable, disable, revoke, and disclosure reload sequence on one exact revision. |
| 2026-09-26 | implemented | Allowed one complete lifecycle to be proven by bounded linked receipts that share artifact, release, environment, and audit identities instead of requiring one monolithic live run. | `current change`; package assurance policy, checker, owner documentation, and focused policy tests. | Retain the operational linked receipt set under Issue #355. This change does not manufacture or replace live evidence. |
| 2026-08-29 | in-progress | Separated the completed local lifecycle mechanics from the missing protected operational receipt and assigned that evidence boundary to Issue #355. | `current change`; existing implementation paths and focused checks in the scope table; [Issue #355](https://github.com/dotnetpower/fdai/issues/355). | Retain the exact-revision governed lifecycle receipt before changing this area to validated. |


### Remaining work

- [ ] Under [Issue #355](https://github.com/dotnetpower/fdai/issues/355), retain a complete
  linked exact-artifact receipt set covering install, enable, disable, revoke, restart, and
  disclosure reload while proving no bundle request bypasses the typed action path. Deferred by the 2026-09-28 owner backlog decision that closed issue `#355` as not planned; open a new issue with exit criteria before scheduling.
