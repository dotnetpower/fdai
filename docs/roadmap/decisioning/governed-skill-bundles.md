---
title: Governed Skill Bundles
---
# Governed Skill Bundles

Governed skill bundles let an operator invoke an ordered, reviewed set of already-installed
runtime skills by one stable identifier. A bundle composes instructions only. It never installs a
missing skill, adds a tool, widens an agent allowlist, approves a change, or executes an action.

> **Scope:** Version 1 supports direct skill members only. Nested bundles and automatic selection
> are not supported. Manual invocation and deterministic workflow attachment are explicit inputs.

## Design at a glance

A canonical JSON manifest declares exact member versions, bundle-level prerequisites, an optional
bounded instruction, provenance, and a self-digest. A detached signature uses the
`fdai.skill-bundle-signature.v1` domain, which is distinct from single-skill and extension
signatures. Installation is disabled-first.

Resolution is atomic. FDAI rechecks the bundle signature and every member's enabled state, exact
version, publisher trust, body digest, tool prerequisites, and agent eligibility. Any failure
returns one stable rejection reason and no member content.

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

## Artifact contract

The public schema is
[`rule-catalog/schema/skill-bundle.schema.json`](../../../rule-catalog/schema/skill-bundle.schema.json).
The canonical parser and domain model live in
[`core/skills/bundle_manifest.py`](../../../services/core-control-plane/src/fdai/core/skills/bundle_manifest.py).

| Field | Contract |
|-------|----------|
| `name`, `version` | Stable lowercase ID and semantic bundle version. |
| `description`, `source` | Human summary and publisher provenance. |
| `members` | Ordered 1-16 skill references with exact `==MAJOR.MINOR.PATCH` constraints. |
| `allowed_agents` | Bundle allowlist. Effective agents are its intersection with every member and runtime. |
| `required_tools` | Complete declared prerequisites. It must cover every member tool and cannot grant one. |
| `instruction` | Optional complete instruction, limited to 8 KiB. It is never truncated. |
| `digest` | SHA-256 of canonical manifest fields excluding the digest slot. |

Unknown keys, duplicate JSON keys, duplicate members, non-canonical bytes, non-exact versions, and
digest mismatch fail at the parser boundary before trust or catalog changes.

## Lifecycle and review

`SkillBundleCatalog` is immutable. Every operation returns a new candidate catalog:

| Transition | Required checks | Rollback |
|------------|-----------------|----------|
| Install | Canonical parser, self-digest, detached publisher signature, unique ID | Uninstall while disabled. |
| Enable | Every member installed, enabled, trusted, exact-version compatible, dependency-complete, and agent-compatible | Disable the same signed manifest. |
| Disable | Installed bundle | Re-enable after the same full validation. |
| Uninstall | Bundle already disabled | Reinstall the retained signed manifest through review. |

`SkillBundleLifecycle` appends content-free events for install, enable, disable, and uninstall. Each
event records actor, reason, timestamp, ID, version, digest, and before/after state. It never records
the bundle instruction or member bodies.

`SkillWorkshop` exposes bundle proposal, review, materialization, and disabled promotion through a
separate bundle proposal store. The proposer cannot self-review. Promotion repeats signature
verification and does not enable the bundle.

## Resolution and capability intersection

The resolver applies these checks in order:

1. Reparse stored canonical bytes and recheck the bundle signature.
2. Detect ambiguous names and dependency cycles. A non-cyclic nested reference is still rejected
   because nested bundles are outside version 1.
3. Intersect bundle, member, requested agent, known agent, and runtime tool eligibility.
4. Load every member completely through the progressive skill disclosure trust path.
5. Check the combined instruction and body budget, then return all members together.

The resolver never returns a prefix. A member update, disable, removal, or trust failure invalidates
the next resolution. A previously resolved immutable value remains replayable for the active
conversation that already owns it.

## Prompt, workflow, and replay

`SkillDisclosureRequest.selected_bundle_names` accepts at most two explicit IDs. The composer does
not rank or auto-select bundles. A workflow can attach the same fixed ID in its deterministic input.

One selected bundle becomes one `skill-bundle` prompt layer containing the complete bundle
instruction and ordered complete member bodies. `PromptReplayManifest.skill_bundle_records`
preserves bundle ID/version/digest, raw manifest SHA-256, member versions and body/raw digests,
selected or rejected status, and rejection reason. The quality-gate audit serializes the same
metadata without private content.

## Runtime and console

Production stores bundle manifests as `trusted_artifact.artifact_kind=skill_bundle`. Migration
`20260720_0042` adds that isolated kind. Startup reconstructs signed skills first, then signed
bundles, and publishes both snapshots to one `RuntimeSkillDisclosure` before serving traffic.

Bragi can use `list_skill_bundles`, `describe_skill_bundle`, and `load_skill_bundle`; exact commands
run deterministically and natural-language turns receive the same schemas. Typed RPC exposes the
same operations under `skill_bundles.*`, all with read scope.

The read-only Governance > Skills panel shows member order, exact versions, dependencies,
compatibility, trust recheck status, and effective eligibility. It has no install, enable, review,
approval, or execution controls.

## Failure reasons

Stable diagnostics distinguish missing, disabled, version-incompatible, untrusted, undeclared
dependency, unavailable tool, disallowed agent, ambiguous name, cycle, unsupported nesting, and
combined-budget failures. Rejection records may include public IDs and digests. They never include
the optional instruction, member bodies, or reference content.

## Verification

Focused coverage includes schema/parser parity, signature-domain separation, lifecycle audit and
rollback, missing/disabled/incompatible members, no-widening intersections, cycle/ambiguity,
member-update invalidation, atomic prompt projection, replay/audit serialization, workshop review,
durable restart, Command Deck invocation, typed RPC, and console decoding.
Release workflow action upgrades must preserve the canonical bundle bytes, detached signature,
digest verification, reproducibility check, and approval boundary; only the artifact transport
implementation may change.

## Related docs

| To learn about | Read |
|----------------|------|
| Progressive single-skill disclosure | [Prompt Composition](prompt-composition.md#reviewed-runtime-skills) |
| Durable trusted artifacts and composition | [Project Structure](../architecture/project-structure.md) |
| Read-only operator inspection | [Operator Console](../interfaces/operator-console.md) |
