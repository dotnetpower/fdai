# Governed Skill Bundles implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Canonical manifest, schema, signature domain, and immutable catalog | implemented | `rule-catalog/schema/skill-bundle.schema.json`; `services/core-control-plane/src/fdai/core/skills/bundle_manifest.py`; `services/core-control-plane/src/fdai/core/skills/bundle_catalog.py`; `services/core-control-plane/tests/core/skills/test_bundle_manifest.py`; `services/core-control-plane/tests/core/skills/test_bundle_catalog.py`; `services/core-control-plane/tests/rule_catalog/schema/test_skill_bundle_schema.py` | Focused tests cover canonical bytes, duplicate and unknown fields, exact versions, self-digests, signature separation, disabled-first installation, no-widening eligibility, atomic resolution, and stable rejection reasons. |
| Audited lifecycle and workshop review | implemented | `services/core-control-plane/src/fdai/core/skills/bundle_lifecycle.py`; `services/core-control-plane/src/fdai/core/skills/bundle_workshop.py`; `services/core-control-plane/tests/core/skills/test_bundle_lifecycle.py`; `services/core-control-plane/tests/core/skills/test_bundle_workshop.py` | Focused tests prove immutable transitions, rollback paths, content-free audit events, no self-review, repeated signature verification, and disabled promotion. |
| Runtime resolution, prompt projection, replay metadata, and quality-gate audit serialization | implemented | `services/core-control-plane/src/fdai/core/skills/runtime.py`; `services/core-control-plane/src/fdai/core/prompts/skill_disclosure.py`; `services/core-control-plane/tests/core/skills/test_bundle_runtime.py`; `services/core-control-plane/tests/core/prompts/test_skill_bundle_disclosure.py` | Focused tests cover complete-member loading, all-or-nothing budget and trust failures, deterministic bundle prompt layers, selected and rejected replay records, and content-free audit metadata. |
| Durable artifact codec, isolated artifact kind, and fail-closed startup reconstruction | implemented | `services/core-control-plane/src/fdai/core/supply_chain/skill_bundle.py`; `services/core-control-plane/src/fdai/core/supply_chain/skill_bundle_loader.py`; `alembic/versions/20260720_0042_skill_bundle_artifacts.py`; `services/core-control-plane/tests/core/supply_chain/test_skill_bundle.py`; `services/core-control-plane/tests/core/supply_chain/test_skill_bundle_loader.py` | Focused tests cover deterministic artifact encoding, malformed archive rejection, digest and identity verification, enabled-state restoration, duplicate rejection, and fail-closed restart behavior. This state does not claim a live database migration or deployed restart. |
| Bragi commands, typed RPC, and read-only Console inspection | in-progress | `services/core-control-plane/src/fdai/core/conversation/skill_discovery.py`; `services/core-control-plane/src/fdai/core/rpc/skill_discovery.py`; `services/core-control-plane/tests/core/skills/test_bundle_surface_parity.py`; `services/core-control-plane/tests/core/rpc/test_skill_discovery.py`; `console/src/routes/skills.tsx`; `console/src/routes/skills.test.ts` | Focused tests now invoke every Bragi and typed RPC bundle operation, prove one stable content-free rejection on both surfaces, prove the read-only reader floor and read-only scope, and prove that Bragi, RPC, and the Console inspection payload answer from the same republished runtime snapshot. They still do not prove that production composition publishes that snapshot before traffic is served. |
| Production composition and governed runtime evidence | in-progress | `services/core-control-plane/src/fdai/core/skills/runtime.py`; `services/core-control-plane/src/fdai/core/supply_chain/skill_bundle_loader.py` | Source and focused tests support implementation claims, but no governed runtime receipt proves migration, restart reconstruction, bundle publication, inspection, resolution, and audit behavior in one deployed flow. No row is therefore `validated`. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. Recorded the focused-test-backed manifest, catalog, lifecycle, workshop, resolution, prompt, replay, artifact, and startup-loader behavior as implemented while separating incomplete delivery-surface evidence and deployed runtime validation. | `current change`; source and focused tests listed in the scope table; the routed core suite (`51 passed`); `uv run pytest -q --no-cov services/core-control-plane/tests/core/rpc/test_skill_discovery.py` (`2 passed`); `npm --prefix console test -- --run src/routes/skills.test.ts` (`3 passed`) | Add direct Bragi and bundle RPC operation coverage; prove live durable restart and production composition; collect governed runtime receipts before claiming `validated`. |
| 2026-08-14 | in-progress | Added direct Bragi and typed RPC bundle-operation coverage and one authoritative-snapshot parity check, and made `describe_skill_bundle` return the same stable rejection as `load_skill_bundle` instead of raising out of the tool. | `current change`; `services/core-control-plane/tests/core/skills/test_bundle_surface_parity.py`; `services/core-control-plane/src/fdai/core/conversation/skill_discovery.py`; focused skills, bundle RPC, and bundle prompt checks passed 72 cases. | Prove production composition publishes the snapshot before traffic is served, apply the durable migration, and collect governed runtime receipts before claiming `validated`. |
| 2026-08-14 | in-progress | Made a refused bundle describe append its own rejection diagnostic, so a metadata read that is denied is visible in the diagnostics ring instead of only at the caller. | `current change`; `services/core-control-plane/src/fdai/core/skills/runtime.py`; `services/core-control-plane/tests/core/skills/test_bundle_surface_parity.py`; focused risk-gate, runbook, skills, RPC, and prompt checks passed 402 cases. | Prove production composition publishes the snapshot before traffic is served, apply the durable migration, and collect governed runtime receipts before claiming `validated`. |

### Remaining work

- [x] Focused Bragi command and typed RPC bundle-operation tests cover list, describe, load,
   rejection behavior, and the read-only control boundary, and prove that Bragi, RPC, and the
   Console inspection payload answer from the same republished runtime bundle snapshot.
- [ ] Apply migration `20260720_0042` to a disposable PostgreSQL database and pass a durable
   install, disable/enable, restart-reconstruction, and tampered-record rejection integration test.
- [ ] Bind signed-skill reconstruction before signed-bundle reconstruction in production
   composition and pass an integration test that publishes both snapshots before traffic is served.
- [ ] Capture governed runtime evidence for durable restart, operator inspection, atomic prompt
   resolution, rejection auditing, and replay before changing any scope row to `validated`.
