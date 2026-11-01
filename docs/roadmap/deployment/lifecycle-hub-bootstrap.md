---
title: Lifecycle Hub Bootstrap
---
# Lifecycle Hub Bootstrap

Use the Lifecycle Hub's local Bootstrap mode to prepare a first FDAI installation through a web
interface. A separate customer-side executor reuses the existing deployment CLI and Terraform;
the Hub interface never receives Azure tokens or Terraform state.

> **Scope:** This is an entry surface for existing installation paths, not a fourth distribution
> path. It does not create a Lite runtime, enroll an installation automatically, or qualify an
> Azure deployment. Local implementation and operational acceptance are separate.

## Design at a glance

One Python command starts two local processes: the Hub setup interface and its customer-side
executor. Neither requires the FDAI Runtime or Hub PostgreSQL to start. Private setup records
are not a replacement for the authoritative Hub database, Terraform state or installation journal.

| Component | Responsibility |
|-----------|----------------|
| Hub Bootstrap interface | Display setup state and exact reviews; submit typed requests and decisions |
| Customer-side executor | Own Azure authentication and run existing preparation, approval, deployment and verification |
| Existing deployment engine | Preserve artifact trust, target bindings, Terraform plans, migration and recovery controls |
| Managed Lifecycle Hub and installation agents | Retain their existing enrollment, ownership, scheduling and update authority |

The executor is a first-install precursor, not another long-lived lifecycle owner. A completed
installation is not automatically adopted by a Lifecycle Agent. Existing ownership acceptance and
state handoff remain separate governed operations.

## Start the local interface

The distribution requires Python 3.12 or later on Linux and a local browser. Install a reviewed
Hub wheel and its declared dependencies from your approved package source, then run:

```bash
fdai-lifecycle-hub start
```

The command selects a free IPv4 loopback port (or falls back to a free port when a requested
`--port` is busy unless `--strict-port` is passed) and opens `/setup` in the browser. On WSL hosts
without `wslview`, the launcher opens the Windows default browser via `powershell.exe`. On headless
or SSH terminals without a browser, the server stays running and saves the owner-only `launch.url`
(`0600`, or prints it when `--print-launch-url` is passed). `fdai-lifecycle-hub status` and
`fdai-lifecycle-hub stop` inspect or stop the local session. Remote Hub configuration cannot enable
this local mode.

This source change does not publish to PyPI. A package name or a locally built wheel alone does
not prove that all required dependency versions are available from an external package index.

## Complete installation

1. Select **Azure sign-in**. The executor synchronizes the operator's local `~/.azure` cache into
   its private profile, supports an optional tenant ID or domain input and device-code sign-in for
   headless terminals, and filters out tenant-level placeholder accounts. Microsoft handles
   authentication; no token is sent to the Hub.
2. Select an accessible subscription, region, monthly cost ceiling, optional workload token, and
   checkpoint approval mode (`continuous` non-destructive default or `stepwise` manual review).
   When no workload token is supplied, the executor automatically selects a non-colliding workload
   name in the target region.
3. Select signed Release Hub images and provide an independently approved Ed25519 public key.
   The executor can retrieve the exact support checkout identified by the verified Release.
   Fetching Terraform and migration support does not authorize service image builds.
   Explicit source mode instead pins the selected clean checkout in an isolated work directory so
   concurrent repository edits cannot interrupt a running deployment.
4. Request preparation. The 15-stage ordered lifecycle panel and progress bar track real-time
   checkpoint and sub-phase progress from the customer executor.
5. Review required checkpoints. In default `continuous` mode, non-destructive checkpoints advance
   automatically once preparation is authorized, while any plan that deletes or replaces resources
   pauses for explicit confirmation. Before any Azure resource mutation occurs, `Reset setup` can
   clear the retained pre-apply configuration so the operator can select another region or target.
6. Wait for application initialization and independent verification. The UI shows ready and enables
   the verified HTTPS Console link only when the existing engine reports `deployment_ready=true`
   and the publication receipt digest matches.

Missing Azure CLI, source tools, trust, permissions, capacity or artifacts produce explicit
blockers. The interface does not acquire subscription privileges, create an Entra application
without permission, weaken a trust check, or silently switch to source builds. The existing signed
offline CLI installation path stays unchanged; this screen does not imply offline onboarding.
The selected support checkout also needs the Bootstrap approval adapter. An older Release without
that protocol is an explicit compatibility blocker, not permission to simulate terminal input.
Hub-image installation keeps the existing minimal, self-reported Release Hub deployment request;
that record is not verified ownership, enrollment or installation success.

## Failure, restart and recovery

Closing the browser does not submit another request or stop the executor. Keep the launcher host
running during installation. One kernel lock prevents duplicate launchers, and the executor
serializes jobs and publishes a current-process heartbeat.

An expired review, dead executor, missing private state, failed verification or uncertain effect
is not success. Restarting preserves the request and original engine records without automatically
replaying effects. Explicit resume uses the retained configuration and existing readback/recovery
path; it cannot change the installation target or artifact source. A changed plan requires its own
current decision.

Do not delete the state directory to clear a failure. It contains installation evidence and
executor-private authentication material. It should remain outside source control, readable only
by its owner. Raw Terraform state, credentials and logs are not exposed through the HTTP API.
App-version rollback, infrastructure recovery and database restoration remain distinct operations.

After verification, Azure-hosted FDAI keeps running when Bootstrap exits. Scheduled managed
updates still need the existing enrollment, accepted ownership and installation Agent prerequisites.
Bootstrap never adds a mandatory per-version update button to a preauthorized lifecycle.

## Design critique and revision

The initial option embedded Azure execution in the Hub server and treated an install click as
blanket approval. It also made a heavyweight deployment portal a prerequisite for installation.
The revised design separates processes, reuses exact decision validators through an explicit
confirmation source, retains private state and heartbeats, and starts without a runtime database.
Release-pinned support source acquisition is distinct from source image builds and never downloads
a trust key beside the catalog as proof of trust.

The local interface accepts exact loopback Host/Origin bindings, bounded JSON, authenticated
sessions and cross-site request forgery protection. Unknown assets and request fields are rejected.
Only bounded setup metadata reaches the interface; diagnostics and credentials stay with the
customer-side executor. The minimal wizard surfaces the authenticated operator identity, required
Azure permission checks with progressive disclosure, explicit runtime platform (`aks` or
`container-apps`) and database placement (`postgres-flex` or `postgres-aks`) choices, a compact
target and connection summary card during active and completed phases, and per-stage start,
completion, and duration telemetry across all 15 stages. Native ownership or enrollment cannot be
inferred from local installation.

## Related docs

| To learn about | Read |
|---------------|------|
| Existing lifecycle authority | [Hub-managed lifecycle](hub-managed-lifecycle.md) |
| Signed image bootstrap | [Release Hub image deployment](hub-image-deployment.md) |
| Explicit source installation | [Source deployment](source-deployment.md) |
| Implementation evidence and limitations | [Bootstrap ledger](../../roadmap-implementation/deployment/lifecycle-hub-bootstrap.md) |
