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

## Artifact contract

The public schema is
[`rule-catalog/schema/skill-bundle.schema.json`](../../../rule-catalog/schema/skill-bundle.schema.json).
The canonical parser and domain model live in
[`core/skills/bundle_manifest.py`](../../../src/fdai/core/skills/bundle_manifest.py).

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

## Related docs

| To learn about | Read |
|----------------|------|
| Progressive single-skill disclosure | [Prompt Composition](prompt-composition.md#reviewed-runtime-skills) |
| Durable trusted artifacts and composition | [Project Structure](../architecture/project-structure.md) |
| Read-only operator inspection | [Operator Console](../interfaces/operator-console.md) |
