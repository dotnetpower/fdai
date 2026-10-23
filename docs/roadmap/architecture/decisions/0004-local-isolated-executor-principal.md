---
title: ADR-0004 Local Isolated Executor Principal for Development Authority
---
# ADR-0004: Local Isolated Executor Principal for Development Authority

This record lets the local execution venue hold a distinct, dedicated executor identity for the
[full-authority development profile](../../decisioning/operator-governance-profiles.md). It keeps
the executor identity separate from the Owner, the Console, and the Core process.

## Status

**Proposed:** 2026-10-22. Design only. No code, configuration, or Azure identity in this record is
implemented.

## Context

The full-authority development profile requires the Owner principal and the executor principal to
be distinct. Today only a deployed runtime holds an executor identity:

- The selection input, `--development-authority-profile`, is accepted only for a source AKS
  deployment, which derives the executor from a managed workload identity.
- The local isolated Executor runs with `FDAI_ISOLATED_EXECUTOR_DEPLOYED=0` and has no Azure
  principal of its own. The local Console and Operator API receive no executor identity by design.
- Local Azure access uses the operator's Azure CLI identity. That identity is the Owner, so it
  can't also be the executor.

As a result, every qualification that needs a real Azure mutation, an independent effect, and a
rollback must run in a deployed installation. That is correct for production. It adds hours of
provisioning, cost, and a slow edit loop to a disposable development scope that the Owner already
controls.

## Decision

FDAI MAY bind one **dedicated local executor principal** to the local isolated Executor process
when, and only when, all of the following hold:

1. The selected approval profile is `full-authority-development` with an exact, current, expiring
   scope. Production profiles, including `single-operator-production`, never use a local executor
   principal.
2. The principal is a dedicated Microsoft Entra service principal created for the profile. It is
   not the Owner, not any human, not the observer, and not a principal shared with another
   installation. The profile's `executor_principal` names its object ID.
3. Its credential is a client certificate whose private key is generated locally, stored with
   owner-only permissions, and readable only by the isolated Executor process. The key never
   appears in the repository, a command line, an environment variable, a log, a chat, or a task
   output. A client secret is not allowed.
4. Its Azure role assignments are limited to the resource groups named in the profile scope. Each
   assignment carries the minimum role for a registered `ActionType`. A subscription-scope or
   tenant-scope assignment fails startup.
5. The certificate and every assignment expire no later than the profile's `valid_until`. Expiry,
   clearing the profile, or failed readback revokes the principal.

### Boundaries that do not change

- Core, the Operator API, and the Console hold only the public principal identifier. Only the
  isolated Executor acquires tokens for it.
- The executor acts only after the existing path completes: schema-validated bus request,
  prepared development binding, exact Owner confirmation, the seven safeguards, and a
  server-issued dry-run digest. The principal grants no approval, promotion, or mode change.
- Independent effect observation uses a separate read identity. The executor can't observe its own
  effect.
- `FDAI_EXECUTION_VENUE=local` keeps its meaning. The evidence profile, action lifecycle, and
  human identity axes from
  [ADR-0002](0002-independent-runtime-axes.md) stay independent.

### Startup verification

The local runtime fails closed unless a live readback proves that:

- the principal exists and is distinct from the Owner and the observer,
- its role assignments are a subset of the profile scope and registered actions,
- its certificate thumbprint matches the profile record and has not expired, and
- no other credential is configured for it.

### Lifecycle

A deployment CLI command creates, rotates, and revokes the principal. Creation records only the
object ID, thumbprint, scope digest, and expiry in a private receipt. Revocation removes the role
assignments before it disables the principal, then reads both back.

## Alternatives

| Option | Outcome |
|--------|---------|
| Deploy-only executor (current) | Keep as the default for production and for installations that need a managed identity. It stays the reference behavior. |
| Reuse the Azure CLI identity as executor | Rejected. It equals the Owner and removes separation of duties. |
| Client secret credential | Rejected. A secret value is easy to leak into logs and environment blocks. |
| Local Core calls the deployed development operations gateway | Viable fallback. It needs a deployed gateway and a caller identity distinct from the Owner, so it doesn't remove the deployment. |
| Workload identity federation from a local process | Not available. A laptop process has no attestable workload identity. |

## Consequences

- **Positive:** a development scope can run a complete mutation, effect-verification, and
  rollback cycle without a deployed installation.
- **Negative:** a stolen local key can act inside the profile scope until it expires. The bounded
  scope, short expiry, owner-only key file, and process isolation limit that exposure.
- **Operational:** the Owner must provision, rotate, and revoke the principal through the CLI.
- **Evidence:** a local cycle proves the mutation path under the development profile. It does not
  replace deployed managed-identity evidence that an issue explicitly requires.

## Implementation slices

Each slice stays in shadow mode and needs its own focused tests.

1. Contract and validator for the local executor principal record, including scope, expiry, and
   distinctness checks.
2. Deployment CLI create, rotate, and revoke commands with private receipts and readback.
3. Isolated Executor certificate credential and the startup readback gate.
4. Local launcher selection of the profile for the local venue, with the same fail-closed checks as
   the deployed path.
5. Focused tests for each refusal: Owner equals executor, wide scope, missing assignment, expired
   or mismatched certificate, extra credential, and production profile.
