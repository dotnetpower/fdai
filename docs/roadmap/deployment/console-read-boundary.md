---
title: Console Read Boundary
---
# Console Read Boundary

This document owns the FDAI Console's local and deployed read-source contract. It keeps source
declarations, authentication, workload evidence, and inventory queries authoritative and
read-only, without giving the Operator API an executor identity.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Read data-source declaration completeness | validated | `fdai_operator_service/composition.py`, focused Operator tests, and an authenticated 53-route Console sweep | Every read route the Console consults resolves to a declared catalog, audit, or durable-table source. A source with no records returns an explicit empty evidence state rather than a synthesized success value. |
| Catalog-backed reference projections | validated | `test_materialize_authoritative_catalogs.py`; authenticated control, capability, promotion, workflow-app, and ownership loads | Reviewed ActionType, Workflow, control, capability, onboarding, scope, and ownership declarations reach revisioned read projections without creating runtime or action evidence. |
| WARA shadow assessment projection | implemented | `fdai_operator_service/composition.py`; WARA projection and workflow-family tests | Local and deployed Operator composition reads the same pinned crosswalk, shadow topic, consumer group, and PostgreSQL projection. Provider observation stays unavailable until separately bound and never falls back to synthetic evidence. |
| Unavailable-surface presentation | validated | Focused Operator and Console checks plus authenticated passes over the affected panels | Unserved routes retain server-owned reasons, and panels do not expose raw transport status or nonexistent configuration symbols. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-01 | implemented | Bound the read-only WARA inventory and optional assessment projection through the shared local and deployed Operator composition boundary. | `current change`; WARA projection, workflow-family, materializer, and Console model checks from the rebased implementation. | Retain a separately authorized multi-resource live-Azure shadow receipt before claiming runtime validation. |
| 2026-08-27 | implemented | Connected catalog, audit, Process, delivery, forecast, memory, skill-source, assurance, readiness, and configuration-baseline status projections to the independent Operator Service. The Operator role receives only the table reads required by those projections. | `current change`; focused Operator tests, strict mypy, Ruff, independent-service checks, materializer checks, and an authenticated 53-route browser sweep. | Provisioning progress and live onboarding still depend on their external observation relays. Python task authoring still depends on its governed provider. |
| 2026-08-18 | implemented | Declared `/kpi/promotion-gates` as an explicitly unavailable read source. The workflow family reads the `promotion-gate.list` projection, but nothing writes it, so the route answered `503` on every Overview and Control assurance load and the console kept requesting it. Declaring the absence lets the client short-circuit and lets the panel state a reason about itself. No gate value is synthesized in either direction. | `current change`; operator suite `406 passed, 1 skipped`; Ruff check and format clean. Measured: the local store holds `rule.list`, `workflow.action-type-list`, and `workflow.catalog` under `operator-projection:workflow:` and zero rows matching `promotion-gate`, and no writer for that key exists in the tree. Mutation-verified by emptying the declared routes, which fails both unavailable-source tests. | Remove the declaration if a promotion-gate producer is introduced. |
| 2026-08-18 | validated | Adopted this focused owner for the Console read boundary and moved its current scope, remaining work, and normative read contract out of the oversized parity document. | `current change`; the six earlier implementation transitions remain unchanged in `dev-and-deploy-parity.md`, and the focused document, translation, route, and size gates pass. | Complete the observable items below without widening the Operator API's authority. |
| 2026-08-27 | implemented | Bound complete ontology instance projections to opaque, process-local selection tokens. The Operator resolves each token against the authenticated principal, ordinary role scope, purpose, exact release, source generation, completeness, and ids before a semantic turn can use it; restart, forgery, and client-recomputed membership fail closed. | `current change`; focused Operator, Core, and Console tests, strict typechecks, Ruff, and translation gates pass. | Retain an authenticated Browser receipt for the complete selection-token path. |

### Remaining work

- [ ] Bind the provisioning progress and live onboarding observation relays, then retain an
  authenticated browser receipt that distinguishes no observed activity from an unavailable relay.
- [ ] Bind the governed Python task authoring provider and retain its no-execution-authority
  capability receipt.

## Design at a glance

The Console resolves a declared server-owned source before each optional read. Missing or
unauthorized evidence stays unavailable, while local and deployed profiles apply the same bounds
and preserve the same read-only authority.

## Source declarations

The read data-source registry declares every route the console consults, including routes this
distribution does not serve. The console resolves a route to its declared source before it sends a
request, so an undeclared route makes it skip that check and issue a request that can only fail;
the panel then loses the server-sourced reason for the empty surface. A surface without a producer
is therefore declared unavailable with a reason instead of being omitted or answered with a
synthesized value, and the console treats that declared unavailability as an optional projection
rather than a page failure. A panel never renders a raw transport status as its operator-facing
message; an unavailable surface shows either the declared reason or its own catalog copy.

## Local authentication

The canonical local Operator API uses `FDAI_OPERATOR_API_LOCAL_ENTRA=1` and shares route-owned
runtime helpers with deployment. The browser obtains the API token and the API verifies its JWT
and App Roles exactly as deployment does. The server's Azure CLI token is confined to Azure
adapters such as Resource Graph, Microsoft Graph, model discovery, and Event Hubs.
`FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1` with `VITE_LOCAL_AZURE_CLI_AUTH=1` is an explicit
CLI-principal debug alternative with a fixed role ceiling.

Cost Governance local review remains authenticated. The explicit
`FDAI_COST_GOVERNANCE_AUTHENTICATED_REVIEW_ACCESS` profile permits disclosure-filtered aggregate
review for a verified principal, but it does not bypass JWT validation, role checks, raw-identity
suppression, package activation, or action authority. Only the Owner-gated Settings route can change
the exact-revision enablement preference.

## Workload evidence

Local Kubernetes workload evidence is opt-in and server-owned. Set `FDAI_LOCAL_KUBECONFIG`,
`FDAI_LOCAL_KUBERNETES_CONTEXT`, and `FDAI_LOCAL_KUBERNETES_CLUSTER_NAME` together to bind one
fixed read-only `kubectl` query. The cluster name must match the Azure inventory result before
Deployment or Pod evidence can complete an AKS answer. With all three values absent, workload
coverage remains explicitly unavailable; a partial binding fails startup instead of using the
implicit current context.

## Inventory queries

Local and deployed inventory projections use the same two query modes. `scope=<view-id>` selects
a deterministic named architecture view. The mutually exclusive rooted mode uses
`root=<resource-id>`, `depth=1..8`, and `limit=1..1000` to return one bidirectional neighborhood;
an unknown root returns `404`, and a cap sets `truncated=true`. The local Azure CLI provider applies
the same bounds to its authoritative cached snapshot that the deployed PostgreSQL provider applies
inside the active snapshot plus real-time overlay. Neither profile widens a rooted request to the
complete inventory. The deployed provider reads that effective graph in one repeatable-read,
read-only transaction, and both profiles expand same-depth frontier resources round-robin in a
deterministic order. Named-view requests keep the original three-argument provider call contract;
only rooted requests require the extended keywords. Relationship-filter count and text length are
bounded before provider dispatch. The read route rejects malformed resources, unknown or dangling
relationships, duplicate resource ids, invalid truncation metadata, and oversized provider output.
Both profiles preserve observed operational state, including nested AKS `powerState.code`, instead
of replacing it with provisioning state. Local cache envelope v13 records a strict redacted receipt
for the Azure CLI/ARG commands that produced the snapshot. Older envelopes refresh before they can
expose provider execution detail. A Command Deck inventory turn applies IQL to that snapshot; it
doesn't claim that the provider commands ran again for the question.

Rooted output uses the requested resource cap and matching edge cap; named views keep the existing
5,000-resource and 40,000-link response ceilings. Both profiles expose the same truncation reason
vocabulary: resource, adjacent-edge, internal-edge, or source cap. The read route rejects unknown
reasons and a reason attached to a non-truncated payload.

## Related documents

| To learn about | Read |
|----------------|------|
| Remaining local and deployed runtime parity | [Runtime Parity](dev-and-deploy-parity.md) |
| Console authority and read surfaces | [Operator Console](../interfaces/operator-console.md) |
| Human identity and App Roles | [User RBAC and Identity](../interfaces/user-rbac-and-identity.md) |
