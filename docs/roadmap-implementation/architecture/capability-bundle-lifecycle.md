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
| Exact-revision governed lifecycle evidence | in-progress | [Issue #355](https://github.com/dotnetpower/fdai/issues/355) | Local mechanics exist, but no protected receipt joins install, enable, disable, revoke, restart, disclosure reload, typed action routing, and audit on one exact revision. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | in-progress | Separated the completed local lifecycle mechanics from the missing protected operational receipt and assigned that evidence boundary to Issue #355. | `current change`; existing implementation paths and focused checks in the scope table; [Issue #355](https://github.com/dotnetpower/fdai/issues/355). | Retain the exact-revision governed lifecycle receipt before changing this area to validated. |
| 2026-08-21 | implemented | Moved the existing capability bundle and trusted-artifact lifecycle into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain governed operational evidence for a complete install, enable, disable, revoke, and disclosure reload sequence on one exact revision. |

### Remaining work

- [ ] Under [Issue #355](https://github.com/dotnetpower/fdai/issues/355), retain one exact-revision governed lifecycle receipt covering install, enable, disable, revoke, restart, and disclosure reload while proving no bundle request bypasses the typed action path.
