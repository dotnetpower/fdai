---
title: Productization and Extensibility Plan
---
# Productization and Extensibility Plan

This document sequences the product and platform capabilities that make FDAI easier to install,
operate, extend, and recover without weakening its cloud-operations control-plane boundaries. It
is the central status matrix for work that spans deployment, conversational channels, capability
bundles, model routing, scheduling, security diagnostics, and developer interfaces.

> **Architecture boundary:** FDAI remains a headless cloud-operations control plane with a thin
> read-only console and governed ChatOps. New interfaces never receive the executor identity and
> every mutation re-enters the typed trust-router, risk-gate, approval, executor, and audit path.
>
> **Implementation focus:** Azure remains the only implemented cloud target. Provider-neutral
> contracts are preserved, but this plan does not add another cloud adapter.
>
> **Status rule:** An item is `implemented` only when executable code and focused tests exist.
> `partial` means a safe foundation exists but a production transport, durable adapter, or release
> artifact still has an explicit exit gate. `planned` means design only.

## Design at a glance

The plan adopts productization features only when they reinforce FDAI's existing architecture.
Install and diagnostics become simple, channels become bidirectional without gaining execution
authority, extensions bind to existing typed capabilities instead of loading arbitrary code, and
background work gains durable ledgers and bounded failover.

| Priority | Meaning | Promotion rule |
|----------|---------|----------------|
| P0 | Required platform foundation | Complete before broadening integrations or user experience |
| P1 | High-value operational experience | Start after its P0 dependency has an executable gate |
| P2 | Conditional expansion | Start only with measured demand and an approved threat model |
| Not adopted | Conflicts with the FDAI app shape | Reconsider only through an architecture decision record |

## P0 platform foundation

| ID | Capability | Status | Exit gate |
|----|------------|--------|-----------|
| P0-01 | Installable `fdaictl` entry point | Implemented | Source and wheel entry point resolve; deterministic `version` text and JSON pass |
| P0-02 | Toolchain and Azure account doctor | Implemented | Missing tools/auth fail closed without printing tenant, account, or user identifiers |
| P0-03 | Secure local onboarding config | Implemented | Schema-validated gitignored JSON is mode `0600`; overwrite requires `--force` |
| P0-04 | Active Azure target mismatch guard | Implemented | Configured and active tenant/subscription mismatch blocks before workflow submission |
| P0-05 | Static deployment preflight | Implemented | Deterministic input, Terraform plan JSON, live Azure Policy/quota/identity/secret, and bounded runner TLS egress pass with hash-only evidence and fail-closed errors |
| P0-06 | Remote plan submission | Implemented | Doctor-gated plan-only dispatch, exact-commit guard, private immutable binary plan, sanitized metadata status, digest/expiry, and bounded cleanup pass without target ids in transport artifacts |
| P0-07 | Exact-plan apply | Implemented | Protected plan requires complete enforce-mode Policy/quota/identity/secret check coverage plus bounded egress evidence; separate immutable evidence digests are restored and verified before claim, approval-gated apply, convergence, migrations, health, and receipt |
| P0-08 | Signed deployment bundle | Implemented | Tracked allowlist, deterministic CycloneDX build/archive, external Ed25519 signing, double-build byte comparison, verifier round-trip, approval-gated artifact, and optional GitHub Release publication pass |
| P0-09 | Local security audit | Implemented | Stable findings cover auth bypass, Entra config, execution flags, sandbox readiness, and config hygiene |
| P0-10 | Narrow security auto-fix | Implemented | Only regular-file `0600` and parent-directory `0700` changes are allowed |
| P0-11 | Bidirectional channel contract | Implemented | Bounded `InboundTurn` and thread-preserving `OutboundResponse` pass protocol tests |
| P0-12 | Channel principal and idempotency gateway | Implemented | Unresolved senders and duplicate message ids reach no tool call |
| P0-13 | Signed Slack-style event ingress | Implemented | Timestamped HMAC, replay window, bot-event rejection, and bounded queue pass |
| P0-14 | Authenticated Teams-style activity normalization | Implemented | RS256 Bot service JWT/JWKS/audience/issuer/serviceUrl checks and bounded same-tenant aadObjectId-to-canonical-principal binding pass before queue admission |
| P0-15 | Production channel publishers and routes | Implemented | Standalone ASGI runtime resolves secret refs, wires signed Slack and concrete Teams auth/publishers, starts gateway consumers, fails startup closed, and cleans routes/tasks/channels/owned HTTP on shutdown |
| P0-16 | Immutable capability bundle runtime | Implemented | Unknown targets/providers fail before the active container changes |
| P0-17 | Trust-verified extension lifecycle | Implemented | Digest, publisher trust, host compatibility, manifest parity, disabled install, and atomic activation pass |
| P0-18 | MCP server registration and discovery | Implemented | Disabled-first catalog, safe endpoint validation, non-invoking `tools/list`, durable revision-CAS state, periodic health, healthy-only routing, and atomic admin audit pass |
| P0-19 | Extension and skill supply-chain policy | Implemented | Domain-separated source-keyed Ed25519 verification, lifecycle-first disabled install, PostgreSQL raw artifact/signature state, exact revision CAS, and restart-safe extension/skill separation pass |
| P0-20 | Durable scheduler dispatch ledger | Implemented | Atomic claim, publish/fail, stale-to-lost reconciliation, retry, migration, and production wiring pass |
| P0-21 | Invariant-safe T2 primary failover | Implemented | Each same-publisher candidate is tried at most once; all-failed still routes to review |
| P0-22 | Typed external RPC and client contract | Implemented | Scoped discovery, strict HTTP correlation, SHA-256 PostgreSQL claim/replay CAS, deterministic compilable Python stubs, built-in tool methods, and explicit standalone production composition pass |
| P0-23 | Governed sandbox profiles | Implemented | Default-deny command, VM-task, MCP/tool, and document-converter profiles enforce server-owned capability, mode, suffix, timeout, workspace/network, and byte ceilings at concrete adapter boundaries |
| P0-24 | Full release verification | Implemented | Approval-gated release waits for clean-checkout full and productization gates, disposable pgvector migration/integration tests, pinned dependency audit, clean-tree confirmation, reproducible signed bundle verification, and optional GitHub Release publication |

## P1 operational experience

| ID | Capability | Dependency | Exit gate |
|----|------------|------------|-----------|
| P1-01 | Stable, beta, and development release channels | P0-08 | Implemented: channel is signed into the manifest; atomic mode-0600 upgrade/rollback state preserves config bytes and rejects channel, CLI-range, version, digest, and history mismatches |
| P1-02 | Portable backup and restore | P0-08 | Implemented: deterministic allowlisted archive restores validated config, opaque references, audit hash metadata, and consented user context without reading or exporting secret-provider values or Terraform state |
| P1-03 | Guided deployment onboarding | P0-02 to P0-08 | Implemented: fail-closed wizard orders toolchain and target doctor, private config, live preflight, plan-only runner submission, and bounded sanitized status post-check without a local apply path |
| P1-04 | Rich Teams and Slack thread behavior | P0-15 | Implemented: bounded vendor-neutral mentions and exclusive stream/edit/reaction intent map to fixed Slack and Teams APIs, capability-off paths preserve the originating thread as text, and accepted sends return typed vendor acknowledgements |
| P1-05 | Channel sender pairing and allowlists | P0-15 | Implemented: atomic durable pending cap and approval, expiring digest, distinct approver, principal resolution, and same-thread native challenge delivery |
| P1-06 | Cross-channel operator identity links | P1-05 | Implemented: only independently approved same-principal senders can form an explicit durable link; distinct principals never merge |
| P1-07 | Multimodal evidence attachments | P0-15 | Implemented: bounded opaque channel attachments pass protected ingestion and become citation-only `doc:` refs; bitmap evidence is metadata-only |
| P1-08 | Managed MCP catalog | P0-18 | Implemented: add/update/enable/disable/remove is revision-CAS, audited, allowlisted, health-checked, healthy-only, and restart-safe |
| P1-09 | Portable skill instructions | P0-19 | Implemented: versioned strict Markdown manifest, publisher trust, tool gates, agent allowlists, and whole-block prompt budget pass |
| P1-10 | Skill proposal workshop | P1-09 | Implemented: inert draft, authorization, distinct review, audit, dedupe, PostgreSQL state-CAS persistence, and trust-verified disabled promotion pass |
| P1-11 | Runtime tool search and describe | P0-18 | Implemented: installed-only RBAC-filtered search, deterministic ranking, and non-invoking descriptors ship through channel verbs and typed read RPC |
| P1-12 | Model health, cooldown, and recovery state | P0-21 | Implemented: role-agnostic redacted failure/recovery/selection transitions persist in PostgreSQL; bounded cooldown and failover remain available when telemetry fails |
| P1-13 | Operator-visible model routing | P1-12 | Implemented: Settings > Models shows selected deployment, redacted fallback reason, cooldown, and recovery without routing controls or provider secrets |
| P1-14 | User-editable durable memory view | Existing operator memory | Implemented: read-only Settings view exposes provenance, scope, expiry, supersession, and approval; edits remain approved HIL/ChatOps workflows |
| P1-15 | Memory compaction and promotion workflow | P1-14 | Implemented: grounded candidates, distinct review, atomic durable promotion, source-preserving rollback, and no action authority pass |
| P1-16 | Expanded schedule types | P0-20 | Implemented: one-shot, interval, IANA-timezone cron, and normalized event-exit schedules persist with kind-qualified deterministic occurrence ids |
| P1-17 | Scheduler run history API and console view | P0-20 | Implemented: reader-role GET panel and read-only console view expose task-scoped status, attempts, failure kind, and stable cursor pagination |
| P1-18 | Scheduled-run isolation profiles | P0-23 | Implemented: durable default-deny profiles bind session/context/tool ceilings and optional command sandbox ids; every scheduled payload carries the profile |
| P1-19 | Typed webhook mappings | P0-22 | Implemented: authenticated server-owned scalar mappings fix allowlisted event/agent targets and derive bounded hashed session keys; invalid payloads publish nothing |
| P1-20 | OpenTelemetry exporter and routing transitions | Existing telemetry | Implemented: secure optional OTLP/gRPC export and bounded stable spans/metrics ship by default for channel, extension, model, scheduler, and security transitions |
| P1-21 | Public extension authoring kit | P0-17 to P0-19 | Implemented: strict template/schema, `fdaictl extension validate`, archive digest, host compatibility, disabled-first, and mandatory security checklist ship together |
| P1-22 | Broader localization coverage | Existing i18n | Implemented: all new CLI/channel/admin surfaces use English fallback or paired catalogs; productization gate enforces catalog parity, translations, and punctuation |
| P1-23 | Heterogeneous model endpoint and gateway contract | P0-21 | Implemented: capability bindings separate Azure OpenAI or self-hosted provider, direct or APIM route, Azure or OpenAI-v1 protocol, Entra audience, typed capacity, features, and verified provenance; core quorum and narrator transports consume the binding fail closed |
| P1-24 | PTU-aware capacity and APIM routing | P1-23 | Implemented: Standard TPM and regional/global/data-zone PTU validate separately, live Model Capacities discovery and exact Terraform PTU counts pass, and an optional existing-APIM policy enforces Entra, managed-identity backends, PTU-first bounded Standard spillover, and durable route evidence without changing day-zero inventory |
| P1-25 | Model endpoint discovery and Settings inventory | P1-23 | Implemented: installable discovery validates concrete Azure OpenAI account/deployment and APIM API/backend/policy state, merges bindings atomically into protected resolved metadata, supports domain-separated signed GPU registration, and projects a sanitized read-only Settings inventory with runtime health |

The public extension kit lives at `examples/extension-kit/extension-kit.template.json` with the
machine schema at `rule-catalog/schema/extension-kit.schema.json`. Run:

```bash
fdaictl extension validate \
  --manifest extension-kit.json \
  --archive extension.zip \
  --host-version 1.0.0
```

Validation is offline. It checks the strict manifest, archive SHA-256, host semantic-version range,
unique capability ids, disabled-first state, and a mandatory security review. Dynamic code,
embedded credentials, direct executor access, network installers, and default-enforce behavior are
schema-level failures.

Runtime trust uses separate `fdai.extension-signature.v1` and `fdai.skill-signature.v1` payload
domains. The configured publisher source selects an Ed25519 public key; the signed payload binds
source, artifact id, version, and archive or raw-Markdown digest. Verified artifacts install
disabled and persist in PostgreSQL with their exact raw bytes and detached signature. Revision-CAS
updates prevent concurrent activation or version replacement, and a durable-write conflict returns
no candidate runtime catalog. The database never stores publisher private keys.

Typed RPC side-effect keys are SHA-256 hashed before PostgreSQL storage. Atomic insert claims one
request across replicas; completed response envelopes replay with the caller's current request id,
while unexpected failures leave an ambiguous in-flight claim instead of retrying a side effect.
Discovery descriptors generate deterministic Python async stubs; normalized method-name collisions
or malformed descriptors fail generation. The standalone production app mounts only health,
built-in non-invoking tool discovery, and explicitly supplied methods behind the caller's
authorizer. It defaults to the durable PostgreSQL claim store.

## P2 conditional expansion

| ID | Capability | Adoption condition | Required guardrail |
|----|------------|--------------------|--------------------|
| P2-01 | Additional messaging channels | Named operator demand and maintainer | Same principal, idempotency, thread, and trust contracts as P0 channels |
| P2-02 | Local model endpoints | Measured disconnected or data-residency need | Approved deployment boundary, model quality floor, and no quality-gate family collapse |
| P2-03 | Subscription-backed model authentication | Approved identity and billing model | Per-capability credentials, cooldown visibility, and no shared operator token in runtime |
| P2-04 | Memory import from external assistants | Migration demand | Preview, conflict handling, backup, provenance, and no credential/transcript import |
| P2-05 | Conditional scheduler watchers | Measured need for state-change triggers | Read-only scripts, strict tool cap, time budget, state-size cap, and separate action payload |
| P2-06 | Proactive operator commitments | Approved notification policy | Explicit opt-in, expiry, same-principal scope, and no inferred mutation |
| P2-07 | OpenAI-compatible read interface | Client interoperability demand | Read-only or proposal-only scope; no executor bypass and explicit auth scopes |
| P2-08 | Additional memory backends | Scale or retrieval evidence | One source of truth, deterministic rebuild, tenant isolation, and measured recall quality |

## Capabilities not adopted

These capabilities do not fit the current FDAI app shape and should not enter implementation by
incremental feature work:

- **General desktop or mobile personal-assistant applications:** The operator console remains a
  thin read surface and ChatOps reaches operators in existing work channels.
- **Wake-word, continuous voice, camera, location, SMS-device, or screen-control nodes:** These
  create a device-trust domain unrelated to cloud-operations control.
- **General browser or full-host computer control:** FDAI uses provider APIs, policy-as-code,
  governed command catalogs, and bounded task runners. It does not automate an operator's logged-in
  browser profile.
- **Arbitrary dynamic code/plugin loading:** Extensions register reviewed typed bundles. They do
  not download and execute unreviewed packages inside the control plane.
- **One shared gateway for mutually untrusted tenants:** Each customer fork and deployment keeps
  its own identities, state, policy, and audit boundary.
- **Console-issued privileged actions:** The console stays read-only. Commands enter through CLI,
  ChatOps, PR, or an authenticated proposal API and follow the standard control loop.

## Delivery order

1. Keep all P0 deployment and release gates enforced as P1 expands.
2. Implement P1 in dependency order: release/backup/onboarding, channel richness, extension and
   skill UX, model health, memory, scheduling, webhooks, observability, and authoring kit.
3. Evaluate each P2 item against measured operator demand, cost, and its threat model.
4. Keep every new action in shadow mode until its own promotion gate passes.

## Verification

Each batch should run the narrowest executable test first, then the affected subsystem suite. A P0
item closes only after these common checks pass where applicable:

```bash
uv run ruff check <changed-paths>
uv run mypy <changed-python-package>
uv run pytest <focused-tests> -q
bash scripts/check-translations.sh
bash scripts/check-punctuation.sh
```

Release batches additionally run `scripts/verify.sh --full` from a clean checkout, build the wheel
and deployment bundle, install the wheel in an isolated environment, verify signatures, and run
migration upgrade checks against a disposable PostgreSQL database. The release workflow enforces
this sequence before its Environment can expose the signing key; a separate dependency audit must
also pass, and only the gated bundle job receives repository write permission.

Run `scripts/verify-productization.sh` for the executable productization gate. It covers the
subsystems in this plan, verifies that Alembic has one head, builds the wheel, and launches
`fdaictl version --output json` through an isolated `uvx` install. It does not replace the full
repository gate or a live disposable-database migration run.

## Related docs

| To learn about | Read |
|----------------|------|
| Cross-subsystem implementation waves | [implementation-plan.md](implementation-plan.md) |
| Install and deployment administration | [../deployment/installable-deployment-cli.md](../deployment/installable-deployment-cli.md) |
| Conversational channels and tools | [../interfaces/operator-console.md](../interfaces/operator-console.md) |
| Capability bundles and DI seams | [../architecture/project-structure.md](../architecture/project-structure.md) |
| Model routing and mixed-model constraints | [../architecture/llm-strategy.md](../architecture/llm-strategy.md) |
| Governed schedules and processes | [../decisioning/process-automation.md](../decisioning/process-automation.md) |
| Security and identities | [../architecture/security-and-identity.md](../architecture/security-and-identity.md) |
