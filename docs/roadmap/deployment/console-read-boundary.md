---
title: Console Read Boundary
---
# Console Read Boundary

This document owns the FDAI Console's local and deployed read-source contract. It keeps source
declarations, authentication, workload evidence, and inventory queries authoritative and
read-only, without giving the Operator API an executor identity.
## Design at a glance

The Console resolves a declared server-owned source before each optional read. Missing or
unauthorized evidence stays unavailable, while local and deployed profiles apply the same bounds
and preserve the same read-only authority.

The complete source registry now has one focused composition owner, while route-family assembly
has another. The production facade keeps authentication, bridge wiring, and readiness. Existing
imports, availability values, durable-source claims, and the no-executor boundary stay unchanged.

## Source declarations

Settings model discovery is a read-only configuration projection, not a workload query or model
invocation. Putting Azure calls in HTTP routes would mix authorization and provider transport;
instead, IAM composition injects a bounded catalog reader into the existing settings projection.
It resolves exactly one account from the configured subscription and model endpoint, reads account
models, deployments, and regional quota, and caches the result for one minute. Explicit refresh
bypasses that cache. Errors clear availability rather than presenting stale data as current.
Catalog presence and deployment success never grant execution, model-selection, or apply authority.

For an explicitly approved local selection, `scripts/deployment/local/bind-existing-model.py`
binds one successful deployment from evidence no older than five minutes into an ignored artifact,
retains an exact backup, and preserves T1 and the independent reviewer. It does not provision or
invoke a model, claim unobserved tool/schema support, or enable a missing T2 verification quorum.

The read data-source registry declares every route the console consults, including routes this
distribution does not serve. The console resolves a route to its declared source before it sends a
request, so an undeclared route makes it skip that check and issue a request that can only fail;
the panel then loses the server-sourced reason for the empty surface. A surface without a producer
is therefore declared unavailable with a reason instead of being omitted or answered with a
synthesized value, and the console treats that declared unavailability as an optional projection
rather than a page failure. A panel never renders a raw transport status as its operator-facing
message; an unavailable surface shows either the declared reason or its own catalog copy.

The `ontology-instances` source groups `/ontology/instances`, `/ontology/instances/explore`, and
`/ontology/instances/states`. Its configuration follows the inventory family store independently
of the generic operational read model. Both venues read the same immutable inventory generation;
an unconfigured store is explicitly unavailable. A configured authoritative source identifies
where records come from, not whether each recorded fact is current. Dashboard v2 and Ontology
Instances preserve that distinction through the [recorded-state contract](../interfaces/recorded-resource-state.md).

## Workflow definitions and Python task capability

The Workflow builder reads two sources that the Operator service answers from its own state
instead of from a materialized `state_kv` projection:

| Route | Operation | Source |
|-------|-----------|--------|
| `GET /workflows/definitions` | `workflow-definition.list` | Direct read of the Operator-owned `workflow_definition` and `workflow_binding` tables |
| `GET /python-tasks/capabilities` | `python-task.capabilities` | The Operator composition's report of the Python task owners it binds |

The definition catalog follows these scoping rules:

- A `global` definition is visible to every authenticated principal, and a `private` definition
  only to its owner. `team` visibility stays excluded until a team-membership source is bound.
- Upstream definitions form **Built-in**, the caller's own definitions form **Mine**, and every
  other visible definition forms **Shared**. A Shared entry withholds its owner reference.
- Bindings are limited to the caller's own automation settings.
- The Operator role has SELECT-only access through the
  `operator_workflow_definition_read_20260929` service migration. After each query, the reader
  repeats the visibility and ownership checks, so a predicate regression fails the read instead of
  disclosing another principal's records.

The capability report returns HTTP `200` with `available: false`, `unavailable_reasons`, and every
operation disabled. The independent Operator binds no Python task validator, VM task runner,
artifact store, author, run submitter, or schedule store. It never holds a VM Run Command
identity, and Core's `FDAI_VM_TASK_ENABLED` executor binding can't make these authoring operations
available. The Console hides the Author Python task control and announces the reported reasons as
a status message.

We chose direct reads over projection producers for two reasons:

- Definitions and bindings are durable, principal-owned records, not repository catalogs. A shared
  projection would need a per-principal key space, a refresh for every write, and a separate
  isolation proof. A request-time read stays bound to the authenticated principal and current
  store state, like the user-context and conversation-assurance reads.
- A capability derived from the composition that serves the routes can't advertise an operation
  that the Operator doesn't serve.

An unreachable store, a missing grant, a malformed record, a record outside the principal scope,
or more than 200 definitions or bindings returns HTTP `503` with an explicit reason. An empty store
returns an explicitly sourced empty catalog. Local and deployed composition use the same reader,
and local preparation and deployment apply the same Operator service migrations. No runtime
writer populates these tables yet: the definition and binding routes queue inert shadow proposals
that nothing consumes, and built-in definitions aren't seeded. Until
[#1655](https://github.com/dotnetpower/fdai/issues/1655) lands that writer, the catalog lists only
records already in the store, and a database created since the service split has none.

## Local authentication

The canonical local Operator API uses `FDAI_OPERATOR_API_LOCAL_ENTRA=1` and shares route-owned
runtime helpers with deployment. The browser obtains the API token and the API verifies its JWT
and App Roles exactly as deployment does. The server's Azure CLI token is confined to Azure
adapters such as Resource Graph, Microsoft Graph, model discovery, and Event Hubs.
Standard preparation selects this Browser Entra mode regardless of stale private Vite values.
Use `prepare-operator-service-env.sh --auth-mode azure-cli` only for the explicit CLI-principal
debug alternative. That alternative has a fixed `Contributor` role ceiling and therefore cannot
open approval details that require `Approver` or `Owner`. The generated API environment sets
`FDAI_OPERATOR_API_LOCAL_AZURE_CLI` and
`FDAI_OPERATOR_API_LOCAL_AZURE_CLI_CONFIRM` together. A direct API launch with only one value
fails configuration validation. The browser applies the same pair rule to
`VITE_LOCAL_AZURE_CLI_AUTH` and `VITE_LOCAL_AZURE_CLI_AUTH_CONFIRM`; a mismatched pair stops
Console startup instead of silently changing the principal.

Cost Governance local review remains authenticated. The explicit
`FDAI_COST_GOVERNANCE_AUTHENTICATED_REVIEW_ACCESS` profile permits disclosure-filtered aggregate
review for a verified principal, but it does not bypass JWT validation, role checks, raw-identity
suppression, package activation, or action authority. Only the Owner-gated Settings route can change
the exact-revision enablement preference.

The header account panel uses the MSAL display name and username for presentation and
`GET /iam/self` for verified FDAI roles. Selecting another account starts the Entra account picker
without a login hint. The redirect returns through normal startup, which acquires a token and
rechecks `GET /iam/self` before rendering the operator shell. This flow stays within the configured
tenant. Directory switching is not supported because the Console and API use one configured issuer.

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
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/console-read-boundary.md) |
| Remaining local and deployed runtime parity | [Runtime Parity](dev-and-deploy-parity.md) |
| Console authority and read surfaces | [Operator Console](../interfaces/operator-console.md) |
| Human identity and App Roles | [User RBAC and Identity](../interfaces/user-rbac-and-identity.md) |
