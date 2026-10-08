---
title: Security and Identity
---
# Security and Identity

Autonomy requires execution privileges, which makes identity and safety the highest-risk surface. Least privilege and reversibility are non-negotiable. This file is authoritative for
the security model; it complements the control loop and safety invariants in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md),
the topology in
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md),
and the code/CI gates in
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md). Declaration-list facets such as `available`, `queryable`, and `readable` express candidate meaning, not authorization. Core constrains the selected declaration kind to the current principal manifest; these facets cannot grant access, create observed state, or bypass the exact-release verifier.
## Severity Vocabulary

- **P0 blocker** - must be resolved and verified before any auto-execution is enabled; blocks
  promotion out of shadow mode.
- **P1** - required before a capability handles production (enforce mode) events.
- **P2** - hardening that may follow first enforce, tracked in Open Decisions with an owner.

## Execution Identity

This section governs the **non-human** executor identity. The **human** identity model -
who signs in to the console and ChatOps, what Entra groups exist, and how the console
delegates writes to a GitHub App - lives in
[user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md). Approval ≠ execution: humans
never hold the executor identity described below.

The default product profile has no executor identity, Entra application, FDAI human role group,
Graph permission, HIL channel, or managed-resource write role. Its Azure observation identity is
scope-bound to `Reader`; deployments select `Monitoring Reader`, `Log Analytics Reader`, `Cost
Management Reader`, `AKS read-only` (Cluster User plus RBAC Reader), or `Storage Blob Data Reader` only
by selecting the corresponding data source. Roles cannot be selected directly or bundled. The
Console and governed-execution add-ons require enterprise identity governance, so no surface can
authenticate a human without its identity prerequisite. The
base requires no Azure Policy assignment; Reader-visible resource metadata supports policy
evaluation, and a source needing more access reports unsupported. `Contributor`, `User Access
Administrator`, Graph application permissions, and every write role remain outside the base.

- The executor MUST authenticate through a **`WorkloadIdentity` interface** that exposes only
  "get a short-lived, audience-scoped OIDC token." This realizes the
  [Workload Identity contract](csp-neutrality.md#4-workload-identity-contract--oidc-token);
  concrete issuers (Managed Identity on Azure, IRSA on AWS, Workload Identity Federation on
  GCP, SPIFFE/SPIRE on any K8s) sit behind that interface, never in `core/`.
- On Azure the interface is backed by a **User-assigned Managed Identity**, scoped to an
  explicit **action whitelist**. No broad standing permissions.
- On Kubernetes, only the isolated Executor ServiceAccount may receive write permissions. Its
  namespace Role is limited to Pod `get` and `delete`, Deployment `get` and `patch`, and
  Deployment scale `get` and `update` for the four registered Kubernetes ActionTypes. Core and
  inventory ServiceAccounts receive no Kubernetes write permission.
- `DefaultAzureCredential()` (or any similarly named SDK entry point) is **prohibited in
  `core/`**; it appears only inside the Azure provider adapter behind the interface.
- **Per-vertical identities are provisioned alongside the aggregate router identity.** Terraform
  creates `id-<workload><suffix>-executor`, `-change`, `-resilience`, and `-finops` identities.
  Fork-owned policy modules bind the vertical action whitelists; see
  [Identity Mapping](#identity-mapping) below.
- human approval identities (HIL) are distinct from execution identities; approval and
  execution are never the same principal, and no identity may assume another domain's identity
  (cross-domain assumption is denied, not just unused).
- Execution identities are **non-interactive**: no interactive/console sign-in, no human
  credentials attached, and disabled for any use outside the event loop.
- The [independent operational evidence](../rules-and-detection/independent-operational-evidence.md)
  verifier is a separate non-executor workload identity. It refuses to start when its principal equals
  any source, producer, reviewer, or executor-class principal, accepts deployed issuance calls only
  from the registered producer workload identity, reads back its own Azure roles at startup, and
  holds only the insert-only proof-store writer role and `EXECUTE` on fixed-parameter
  `SECURITY DEFINER` source functions, never a direct `SELECT` on a source view or table. A purpose is
  bound only when its source is read under the verifier's own identity from a store another principal
  writes; rows that the producer or Operator can write never stand in for a platform or inventory
  source, so readbacks without such a source stay unbound.
- Prefer **credential-free auth**: workload identity federation / OIDC token exchange so the
  executor holds no long-lived secret. Where a secret is unavoidable it is short-lived and
  auto-rotated (see Secrets and Config).

### Identity Mapping

This resolves the P0 Open Decision *"Executor-side identity mapping"*. The current Terraform
shape preserves one aggregate action-router identity and three vertical identities so delivery
adapters can select a principal by domain without changing `core/`.

| Identity | Current purpose | Azure role strategy | Scope |
|----------|-----------------|---------------------|-------|
| `id-<workload><suffix>-executor` | aggregate control-loop transport and action routing | upstream grants only platform roles needed by the runtime, such as topic-scoped Event Hubs access and Key Vault secret reads | resource or service scoped; never subscription-wide |
| `id-<workload><suffix>-change` | Change Safety delivery principal | fork-owned action whitelist or measured custom role | governed resource groups for Change Safety |
| `id-<workload><suffix>-resilience` | Resilience and recovery delivery principal | fork-owned action whitelist or measured custom role | governed recovery scopes |
| `id-<workload><suffix>-finops` | Cost Governance delivery principal | fork-owned action whitelist or measured custom role | governed cost-optimization scopes |

Execution authorization uses provider-neutral refs `identity/change`, `identity/resilience`, and
`identity/finops`. Terraform attaches the corresponding UAMIs and exposes only their client ids to
the delivery composition. The authorization result selects one ref; the Action and direct-API
request preserve it, and the delivery router chooses the matching `WorkloadIdentity`. An unknown
or unbound ref is refused rather than falling back to the aggregate executor identity.
Alert-noise actions never reach a generic direct-API fallback: an alert-specific unavailable route
holds them in shadow and enforce mode, and other direct-API actions keep the unwired-executor rejection.

Read-only inventory, ingestion, canary, and other service identities remain separate from this
executor set. Creating a vertical identity does not grant it resource permissions; those role
assignments are explicit fork deployment policy.

Rules that apply to every phase (MUST):

- **RG-scoped, never subscription-wide.** A new RG comes under governance only when the
  fork explicitly adds it to the assignment IaC - no automatic broadening.
- **Complementary Azure Policy `deny`** blocks any MI action outside its declared
  whitelist as a second line of defense, so a mis-assigned role cannot silently widen
  the surface.
- **Every action whitelist change is a governance PR** with `Justification:` and
  Owner-tier quorum on any change touching a Managed Identity role assignment
  ([user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md)).
- **Shadow log capture** records every action emitted by the
  executor MI in shadow mode records the exact Azure resource-provider operation it
  would call, so the Phase 2 Custom Role derivation is deterministic and auditable.

The delivery layer selects a vertical MI from the action domain; no core code change is needed.

## Authorization Model

Execution authorization resolves through the provider-neutral capability ontology and scoped
policy assignments described in
[Execution Authorization Ontology](../decisioning/execution-authorization-ontology.md). Action
approval never grants executor access. A missing permission holds the original action and may
create a separate exact-plan `AccessGrantRequest`; a distinct protected deployer applies an
approved grant, and fresh effective-access evidence is required before the action is re-evaluated.

- Map every action to the minimum role/permission needed; **deny by default**.
- Enforce least privilege mechanically, not by convention: the action whitelist is
  policy-as-code (OPA/Rego) evaluated at the risk gate, and privileged scopes are granted
  **just-in-time and time-bound**, expiring after the action window rather than standing open.
- Reconcile the org's account/identity standard with the cloud authorization path (e.g. an
  external IdP such as Keycloak ↔ Entra ↔ Managed Identity). Treat this mapping as a **P0
  blocker**; it is resolved only when the end-to-end path is provisioned, tested with a
  least-privilege probe, and access recertification is scheduled.
- **Access recertification**: role assignments are reviewed on a fixed cadence; unused or
  over-broad grants are revoked. Recertification outcomes are audited.
- Autonomous deployments must respect platform policy (e.g. Azure Policy `deny`); provide a
  **policy-exemption workflow** (requestable, time-boxed, audited, owner-approved) rather than
  bypassing controls.

## Secrets and Config

- Never hardcode secrets, connection strings, subscription/tenant IDs, or customer identifiers.
  Secret scanning (e.g. gitleaks) runs in CI and a positive finding blocks the merge
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- **The app reads only environment variables (or K8s Secret mounts).** It MUST NOT call a CSP
  secret SDK (`SecretClient`, `SecretsManagerClient`, `SecretManagerServiceClient`, ...); this
  realizes the [Secret contract](csp-neutrality.md#3-secret-contract--environment--k8s-secret).
  On the AKS baseline, the injection layer is the **managed Key Vault CSI provider + workload
  identity**, which synchronizes fixed references into namespaced Kubernetes Secrets. Existing
  Container Apps installations retain native Key Vault references only as a compatibility path.
- Access secrets through an injected `SecretProvider` in `shared/providers/`, never a global
  read at import.
- **Lifecycle**: every secret has an owner, a defined rotation interval, and automated rotation;
  compromised or superseded material is revoked immediately. Prefer federated tokens so there
  is no secret to rotate.
- **Fail-closed**: if the secret injection layer or token issuer is unavailable at startup, the
  process fails fast - it does not fall back to a cached or embedded credential and never
  starts in a degraded state.
- Secrets MUST NOT appear in logs, audit entries, error messages, test fixtures, or LLM prompts.
- Keep the repo customer-agnostic
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## Data Protection

- **Classify** data handled by the control plane (event payloads, tool output, audit records,
  embeddings) and minimize it: store pointers/ids, not raw customer bytes or PII.
- Encrypt in transit (TLS) and at rest; keys are managed in the secret/key store, not in code.
- **LLM data handling**: T2 prompts are redacted of secrets and PII before leaving the trust
  boundary; enforce data-residency and no-retention terms for any external model vendor. A
  prompt that would require unredactable sensitive data is routed to HIL instead of sent.
- **Evidence-source isolation**: Independent read-only sources use separate finite deadlines. One
  source timeout cannot discard evidence already completed by another source, and unavailable or
  empty evidence never becomes a healthy observation, a cause claim, or execution authority.
- **Code-security remediation packs**: a pack carries undisclosed vulnerability detail to
  developer machines and their coding-agent services. Export requires a deployment-approved
  provider (data residency, no training, retention, and allowed pack modes), a signed manifest,
  and a registry record; result import trusts only that record. Notifications and agent bus
  messages carry counts and opaque issue ids, never code or paths. See
  [Code Security Findings](../operations/code-security-findings.md#remediation-pack).
- **Code-security LLM lens**: the optional lens lane sends bounded source excerpts to configured
  model deployments, so the same residency and no-retention terms apply. Its output is untrusted;
  only grounded, quorum-agreed candidates become inert hypotheses. Grounding is checked in code: a
  cited line must be a sink-hint line or a variable assignment that a later sink-hint line of the
  same excerpt uses, and the hypothesis is anchored at that sink. The `evaluate-lens` precision
  measurement sends excerpts only from a pinned public benchmark sample staged in an owner-only
  scratch root, never from a customer repository.
- **Code-security proof lane**: the only place FDAI runs repository code. It's opt-in per scan,
  limited to issues a deterministic verifier already confirmed, and runs in a disposable
  bubblewrap sandbox with no network, no credentials, a cleared environment, a read-only source,
  and resource limits. Every sink is a recording hook, so a proof never performs the real effect.
  Native memory-safety proofs, which no verifier confirms, need a deterministic or external report
  and compile the target with sanitizers. That run alone drops the sandbox address-space limit,
  which AddressSanitizer can't run under; the harness limits the compiler's address space and
  every run's CPU time, resident memory, wall-clock time, and output instead.
- **Code-security repository scans**: a Console scan request only queues a typed proposal for a
  registered alias and grants no approval or execution authority. The scan worker narrows each
  GitHub App token to that one repository with read-only contents permission and passes it to git
  only through environment configuration, never argv, logs, or the extracted tree. Only an Owner
  can register or toggle a repository, and the worker rechecks that role. Console issue summaries
  are bounded, bound to their review digest, and carry no path, line, symbol, scanner message,
  or code. Local folder scan reports are owner-only files without code, scanner messages, or
  secret values. See
  [Code Security Scanning](../operations/code-security-scanning.md#repository-scans-from-the-console).

## Network Boundaries

- The executor and core engine have **no public inbound endpoint**; ingress is the event bus
  only. Management/API surfaces sit behind private networking.
- **Egress is allow-listed** to required cloud control planes and model endpoints; default-deny
  outbound to contain exfiltration and injection-driven callbacks.
- Layer identities are not shared across the network boundary; the console, including its optional
  policy-administration add-on, and ChatOps never hold the executor identity
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).

## Supply-Chain Integrity

- Dependencies are pinned via lockfile; CI installs from the lockfile only and a vulnerability
  scan blocks high-severity findings.
- The rule catalog and IaC are catalog-as-code behind **protected branches with signed
  commits/PR review**; no direct pushes to the enforce branch.
- Build artifacts (container images) are signed and their provenance/SBOM recorded; the
  executor pulls only verified, pinned digests, never mutable `latest` tags.

## Seven safeguards (every autonomous state-changing action)

1. **Stop-condition** - a defined halt state that aborts the action. Declared per-ActionType
   in `stop_conditions[]` and evaluated by the executor during and after apply.
2. **Rollback path** - a tested way to revert. The ontology `ActionType.rollback_contract`
   MUST be one of `pr_revert` / `scripted` / `pitr` / `snapshot_restore` /
   `state_forward_only`; **`none` is not a valid value**. Genuinely one-way mutations set
   `ActionType.irreversible: true` and are routed HIL+quorum by the risk-gate; rollback is
   still declared as the best-effort recovery.
3. **Blast-radius limit** - scope caps (non-prod first, batch size, rate) plus per-resource
   serialization so concurrent actions on one resource are mutually excluded. `ActionType.blast_radius.computation = graph_derived`
   makes the risk-gate compute the actual impacted set over the Resource → Resource graph
   (`contains` + reverse `depends_on`, depth 2) - the three-value enum is a bucket, not a cap.
4. **What-if or dry-run** - a successful, version-bound prediction receipt before mutation.
5. **Logical-target lock** - a held lock and causal ordering for every affected target; managed
  resource changes use the exact resource identity.
6. **Idempotency** - a stable key and duplicate suppression across delivery and retries.
7. **Audit lifecycle** - append-only intent persisted before the side effect, then terminal
  execution and outcome closure after it.

Missing any safeguard means the action is incomplete and must not ship. Each safeguard is
**testable**: shadow-mode tests prove no mutation, rollback tests prove prior state is restored,
and property-based tests assert that high-impact execution has current or standing human approval,
silence grants nothing, irreversible actions never use standing authorization, and retries are
no-ops. Pure A0 reads follow their bounded read authorization and evidence contracts rather than
mutation rollback, dry-run, and lock requirements. Independent effect verification gates every
success claim.

### Target-lock ownership migration

The evidenced target lock has one owner per mutation path. The migration keeps the legacy
resource-claim fence until the selected executor is readiness-gated on the evidenced provider.
It does not permit a temporary dual acquisition.

| Path | Current target-lock boundary | Required owner after migration |
|------|------------------------------|--------------------------------|
| Thor dispatch | Legacy target lock around the generic executor call plus a separate durable resource claim | Keep the durable claim. Remove the duplicate target lock only when the selected executor rejects a missing evidenced provider. |
| PR native/manual | Idempotency mutex, then an internal legacy target lock | The selected PR executor owns one evidenced target lock through publish and terminal persistence. |
| Direct API | Idempotency mutex, then an internal legacy target lock | The direct-API executor owns one evidenced target lock through provider commit continuity and terminal persistence. |
| Tool call | Idempotency mutex, then an internal legacy target lock | The tool-call executor owns one evidenced target lock through provider commit continuity and terminal persistence. |
| Workflow | Orchestrates the selected executor and does not define a separate `ExecutionPath` | The selected executor owns the target lock. Workflow passes the immutable pre-bundle commitment and never reacquires the target. |
| Isolated Executor | Shared-bundle revalidation remains open under #628 | The isolated executor must reject missing or stale evidenced ownership before dispatch and must not fall back to the legacy seam. |
| Governed chaos catalog | The adapter holds the injected distributed lock on every canonical target identity, a durable per-target run claim, and an exclusive `injecting` compare-and-swap before the harness runs. A claim passes on only after verified recovery, denial, failure without an injection attempt, or a separate audited Var closure decision | The runtime binding in `runtime/delivery.py` must hand the adapter one evidenced target lock without re-entering the tool-call executor's own target lock (#94). |

### PostgreSQL continuity admission

An effect sink is unsupported for production until its composition supplies one reviewed
`EffectSinkContinuityPolicy`. The policy selects fenced and idempotent execution, complete
lock-session atomicity, or cancellation with durable unknown-outcome quarantine and authoritative
reconciliation. A generic Direct API or tool category is not a continuity strategy.

The PostgreSQL evidence provider follows these boundaries:

- One dedicated connection owns the exact advisory key for the complete acquisition context.
  Reconnect or connection substitution creates a new acquisition and cannot continue the old one.
- The acquisition binds the database identity, backend process ID, backend session discriminator,
  request digest, and owner-reference digest without storing the DSN or a capability-bearing token.
- `pg_locks` with `granted=true` is a point-in-time substrate observation. Provider-owned UTC time
  and the five-second contract maximum bound the assessment, but neither predicts future ownership.
- The provider checks the boolean advisory-unlock result. A connection loss, missing lock row, or
  unknown unlock result produces lost or unknown release evidence and durable target quarantine.
- A sink commit does not clear quarantine or claim operational success. The selected sink policy
  must provide stable sink idempotency or authoritative status reconciliation, and independent
  effect verification remains a separate terminal axis.

## Rate Limiting and Kill-Switch (DoS and containment)

- The event loop and executor enforce **rate/budget caps** (per-tier, per-resource, and global);
  exceeding a cap degrades to HIL, never to ungated auto-action. This also bounds cost and a
  runaway or event-flood (DoS) condition.
- A **global kill-switch** halts all auto-execution immediately and drops every path to
  shadow/HIL; it is operable without the executor identity. The risk gate realizes this via a
  `kill_switch` ceiling axis fed by `KillSwitch.is_engaged()`
  ([execution-model.md](../decisioning/execution-model.md) 2.6b). The production runtime reads
  the state from PostgreSQL before every authority decision; a read failure is treated as
  engaged. Owner and Break-Glass principals change it through `POST /system/kill-switch`, which
  uses revision compare-and-set and writes the audit entry in the same transaction.
- A **break-glass** procedure grants scoped emergency access under mandatory audit and
  post-incident review; break-glass use raises an alert and auto-expires.

## Shadow → Enforce Promotion

- New capabilities ship in **shadow mode**: judge and log only, no execution.
- Promotion to enforce is explicit, per-action, and gated on a **minimum shadow duration and
  sample size**, measured accuracy above threshold, and **zero policy-violation escapes** in
  shadow (metrics defined in [goals-and-metrics.md](goals-and-metrics.md)).
- An authorized installation operator may also promote a capability before its gate passes. This
  attributed override records the gate status at that time, stays marked on every surface, never
  counts as promotion evidence elsewhere, and yields to regression demotion and vendor capability
  recall ([Operator Governance Profiles](../decisioning/operator-governance-profiles.md)). The
  promotion registry stores `promotion_kind` and accepts an override only after an injected
  verifier confirms its Var approval receipt; the `governance.override-promote-action-type` path
  issues and verifies that receipt through Thor's direct promotion adapter.
- Regressions demote back to shadow automatically; every promotion and demotion writes an
  audit entry.
- Working-context policy candidates use the same capability authority without gaining action
  capability. They install disabled, run bounded off-path comparisons, require an exact version,
  evidence window, and rollback target for promotion, and engage a per-policy kill switch on an
  invariant violation. See [Context Selection Policy](../decisioning/context-selection-policy.md).
  Core shutdown gives pending comparisons five seconds to finish before cancelling them and
  closing the state store. An interrupted comparison cannot become promotion evidence.
- Operator-authored policy revisions are signed by Mimir with a non-exportable installation key and
  retain the raw signature, versioned key id, and signed-message format. Core verifies that
  signature before activation and before using an active revision in the admission-policy or
  approval-profile path. Missing, tampered, or wrong-key signatures fail closed to no activation or
  human approval.
- The T2 hallucination rubric leg follows the same evidence rule and gains no authority. Its mode
  is resolved per ActionType from an independently verified receipt, and only when the deployment
  binds the receipt source and verifier. A missing, expired, rejected, or mismatched receipt keeps
  it in shadow, and in enforce mode it can only lower confidence. See
  [Hallucination Rubric Gate](../decisioning/hallucination-rubric-gate.md).

## Human Approval Integrity

- Approval and execution are distinct principals; **no self-approval**, and high-blast-radius
  actions require **quorum (multi-approver)** rather than a single approver. The single-operator
  production profile is the only production exception: one named operator may approve, and the
  audit records the original quorum with an effective quorum of one
  ([Operator Governance Profiles](../decisioning/operator-governance-profiles.md)). Core implements
  this decision rule; runtime approval paths don't pass an active profile revision yet.
- Approvers authenticate with MFA/phishing-resistant credentials; each approval is bound to a
  specific action + idempotency key so it **cannot be replayed** against a different action.
- **Timeout is fail-closed**: an HIL item without current approval or a valid pre-existing standing
  approval ends as a no-op plus an audit entry. Silence never creates approval. A standing approval
  applies only through the bounded A3-E contract in
  [Escalation and Standing Authority](../decisioning/escalation-and-standing-authority.md).
- A decision message on the event bus is transport, not approval. The Operator records its durable
  decision receipt in the same transaction that validates the pending approval, and Core routes a
  decision only when the message matches that receipt. A forged or rewritten message is refused
  before any park, quorum slot, or executor is touched.
- Approval requests travel only through A1 routes. The notification router refuses to deliver an
  A1 message through a route of another tier and escalates it to the HIL sink, so a routing
  change outside A1 can't redirect a decision-bearing callback. That is why only A1 routing
  changes need the governance identity attestation
  ([Rule Governance](../rules-and-detection/rule-governance.md#notification-routing-scope)).

## Auditability

- The audit store is append-only and is the trust basis for autonomy.
- **Tamper-evidence**: entries are hash-chained (each record commits to the previous) and
  periodically anchored/signed, so deletion or edits are detectable; storage is
  write-once/WORM where available.
- **Non-repudiation**: each entry records the authenticated actor identity (executor or
  approver) and mode (shadow/enforce) so an action cannot later be disowned.
- Every action links to: the triggering event, the tier that decided it, the rules/policies
  cited, the risk decision (auto/HIL), the approver (if HIL), the idempotency key, and the
  rollback reference.
- **Retention**: a defined immutable retention window with legal-hold support; records are not
  purgeable before the window elapses.
- Audit data is customer-agnostic in this repo; real environment records live only in a fork's
  runtime store, never committed here.
- A [shadow-only MSCP decision context](mscp-operational-profile.md#adopted-mechanisms) records
  its content digest with the first immutable state write and one sanitized audit entry. Missing or
  conflicting owner observations hold; a replay cannot replace that record. This projection does
  not establish approval, execution, or operational evidence without authoritative runtime readers.

## Threat Model (STRIDE)

Browser-only evidence uses a separate credential-free runtime with no executor identity or host
filesystem mount. Exact HTTPS origin policies, per-connection DNS revalidation, restricted egress,
GET/HEAD interception, visual and text redaction, secret canaries, prompt-injection scanning,
content hashes, and append-only custody records form one fail-closed boundary. Browser content is
always untrusted and cannot approve or execute an action. See
[Browser evidence collection](../interfaces/browser-evidence.md).
The Operator role can select only admitted payload-free workspace metadata and one fixed
snapshot-wide withheld aggregate. It cannot select the artifact table or the internal admission
view. Withheld output contains counts only, and custody navigation appears only for one exact actor,
action, digest, trust, and no-authority audit match. Ambiguous or malformed matches expose no
sequence or correlation identity.

Event payloads and tool output are **untrusted**; the deterministic verifier and policy
re-check are the authority, never model or event text.
Provider observation failures cross service boundaries only as allowlisted machine reasons.
Raw provider response text is neither persisted as Resource state nor returned to the Console.

| STRIDE | Threat | Mitigation |
|--------|--------|------------|
| **Spoofing** | Forged events / impersonated approver | Authenticated (signed) event source; MFA + action-bound approvals; federated identity |
| **Tampering** | Altered rules/IaC, injected artifacts | Signed commits, protected branches, signed/pinned artifacts + SBOM |
| **Repudiation** | Action later disowned | Hash-chained, actor-attributed append-only audit |
| **Info disclosure** | Secret/PII leak via logs or LLM prompts | Redaction, no-secret-in-prompt, encryption, egress allow-list |
| **DoS** | Event flood / runaway loop / budget burn | Rate/budget caps, circuit-break to HIL, kill-switch |
| **Elevation** | Over-broad or cross-domain action | Per-domain identities, JIT time-bound scopes, deny cross-assumption, no self-approval |
| **Prompt injection** | Malicious payload steers T2 | T2 treated as untrusted; verifier + policy re-check are authoritative |

## Open Decisions

| Priority | Decision | Owner | Target |
|----------|----------|-------|--------|
| ~~P0~~ | ~~Executor-side identity mapping~~ - **resolved** in [Identity Mapping](#identity-mapping) | - | - |
| ~~P0~~ | ~~Risk-classification policy (auto vs HIL) and initial policy approver~~ - **resolved** in [risk-classification.md](../decisioning/risk-classification.md) | - | - |
| P1 | Policy-exemption workflow owner and SLA | TBD | before production |
| P1 | Audit anchor cadence, WORM binding, and operational verification | TBD | before production |
| P1 | Kill-switch and break-glass runbook and drill schedule | TBD | before production |
| P2 | Compliance control mapping (MCSB / CIS / SOC 2) and evidence collection | TBD | post first enforce |
| P2 | Secret rotation intervals and federation coverage per identity | TBD | post first enforce |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/security-and-identity.md) |
