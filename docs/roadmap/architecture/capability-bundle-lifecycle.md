---
title: Capability bundle lifecycle
---
# Capability bundle lifecycle

This document defines how a fork registers a discoverable capability, verifies its artifacts, and
moves it through install, enable, disable, and uninstall without creating another execution path.
It refines the dependency-injection model in [Project Structure](project-structure.md) and keeps all
mutating requests on the ordinary trust, risk, execution, recovery, and audit path.

> **Authority boundary:** Bundle and extension activation registers typed metadata, references,
> and reviewed providers only. It never grants approval or execution authority.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Bundle validation and immutable runtime registration | implemented | `core/capability_catalog/`; `composition/install_capability_bundle`; focused capability catalog tests | Unknown targets, provider mismatches, duplicate ids, and dangling references block activation without changing the current runtime. |
| Durable trusted artifacts and skill disclosure | implemented | `core/supply_chain/`; `delivery/trust/`; PostgreSQL trusted-artifact adapters | Artifacts retain exact content, signature, publisher, state, and revision; runtime disclosure is rebuilt from reverified records. |
| Governed external skill source lifecycle | implemented | `core/skills/source_registry.py`; `core/supply_chain/skill_source_*.py`; skill source API routes | Installation starts disabled, revocation preserves provenance, and production reloads disclosure after a command. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-21 | implemented | Moved the existing capability bundle and trusted-artifact lifecycle into a focused owner document without changing runtime behavior or authority. | `current change`; document-size, translation, route, and link checks. | Retain governed operational evidence for a complete install, enable, disable, revoke, and disclosure reload sequence on one exact revision. |

### Remaining work

- [ ] Retain one exact-revision governed lifecycle receipt covering install, enable, disable,
  revoke, and disclosure reload while proving no bundle request bypasses the typed action path.

## Bundle registration

Use a `CapabilityBundle` when a fork adds a discoverable capability rather than replacing one
infrastructure seam. A bundle groups the operator-facing `Capability` metadata, one typed
`CapabilityBinding`, optional reviewed `ToolArtifact` metadata, and any reasoning-tool
`ToolProvider` implementations. A binding points to either an already loaded reasoning tool or a
tool carried by the same bundle, or to an existing `ActionType` or `Workflow`. It does not define
another execution path or load provider code from an artifact.

Install a bundle with `fdai.composition.install_capability_bundle(...)`. The installer builds
cross-references from the loaded catalogs and returns a new `Container` whose
`capability_runtime` contains the validated registration. Startup is blocked when a target is
unknown, a provider is missing or duplicated, a tool's declared provider does not match the
bundle, a package tool is unreferenced, or a package tool id shadows another source. The input
container remains unchanged when validation fails.

`wire_azure_container(...)` combines the file-backed tool catalog with package tools from the
installed runtime, then combines runtime providers with explicit
`AzureWireOverrides.tool_providers`. Duplicate tool or provider ids are configuration errors
rather than implicit overrides. `ActionType` and `Workflow` bindings are references only: mutating
requests still re-enter the trust router, risk gate, executor, and audit path. See the
[Core package root](../../../services/core-control-plane/src/fdai/) for a copy-ready read-only
provider and bundle.

## Extension lifecycle

When a deployment needs install, enable, disable, or uninstall lifecycle around those bundles, use
`ExtensionManager` in `core/capability_catalog/extensions.py`. Installation verifies the archive
SHA-256 digest, an injected publisher trust decision, host-version compatibility, and manifest-to-
bundle capability parity. A verified extension is installed disabled. Enabling it rebuilds a
candidate `CapabilityRuntime` from the immutable base and every enabled bundle, so an unknown
ActionType, Workflow, reasoning tool, or provider blocks activation without changing the current
manager. Disable the extension before uninstalling it.

This lifecycle is intentionally not a dynamic code loader or public package downloader. The fork
composition root supplies already-reviewed provider implementations and the trust verifier.
Extension activation registers typed metadata and references only; every mutation still uses the
normal pipeline and starts in shadow mode according to its ActionType or Workflow contract.

## Trusted artifact persistence

`core/supply_chain/` owns the durable trusted-artifact contract and install orchestration shared by
extensions and skills. Installation first passes the existing extension or skill lifecycle, then
persists the exact raw artifact, detached signature, publisher source, digest, and disabled state.
A failed durable write returns no candidate catalog to the caller. `delivery/trust/` provides the
concrete source-keyed Ed25519 verifiers with distinct extension and skill signature domains, so a
signature cannot replay across artifact kind, source, id, version, or content digest.

Production uses `PostgresTrustedArtifactStore` and the `trusted_artifact` table. Extension and skill
ids share one schema but remain separated by `artifact_kind`; insert requires expected revision 0,
and every update requires an exact revision and increments by one. The table repeats the content
size, SHA-256, 64-byte signature, state, timestamp, and revision constraints. It stores no private
key or provider credential. Production Operator API startup loads skill records, resolves publisher
public keys from `FDAI_SKILL_TRUSTED_PUBLISHERS_PATH`, and atomically publishes a reverified
`RuntimeSkillDisclosure` shared by Bragi, optional typed RPC, and the GET-only Skills panel. Local
composition publishes an empty fail-closed snapshot when no durable skill store is configured.

Governed multi-skill manifests use the separate `skill_bundle` artifact kind and
`fdai.skill-bundle-signature.v1` domain. Startup rebuilds skills before bundles so exact member
versions and enabled state are validated before the shared runtime snapshot is published. The
three read surfaces share that one snapshot: republishing it moves the Bragi commands, the read-
scoped `skill_bundles.*` RPC operations, and the Skills panel inspection payload together. Every
bundle rejection returns one stable content-free reason drawn from a fixed English token
vocabulary. A refused describe and a refused load each append their own rejection diagnostic, and
an unbound bundle catalog is one of those stable reasons rather than a caller-parameter error.
Listing an unbound catalog still reports zero, because with no catalog bound nothing is installed.

## External skill sources

Approved external skill repositories use the separate durable source pipeline in
[Skill Source Management](../interfaces/skill-source-management.md).
`core/skills/source_registry.py` owns immutable source identity;
`core/supply_chain/skill_source_*.py` owns quarantine, disabled candidate approval, scheduled ETag
refresh, and revocation policy. PostgreSQL adapters persist the five Alembic `0045` tables. Reader
GET routes expose source evidence, while separate Approver and Owner POST routes install disabled
candidates or revoke without deleting provenance. Production reloads the runtime disclosure after
either command so durable disablement takes effect immediately.

## Related docs

| To learn about | Read |
|----------------|------|
| Composition roots and injectable seams | [Project Structure](project-structure.md#customization-via-dependency-injection) |
| Downstream registration procedure | [Downstream Fork Guide](../fork-and-sequencing/downstream-fork-guide.md) |
| Durable external skill sources | [Skill Source Management](../interfaces/skill-source-management.md) |
