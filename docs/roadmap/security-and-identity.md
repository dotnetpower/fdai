# Security and Identity

Autonomy requires execution privileges, which makes identity and safety the highest-risk
surface. Least privilege and reversibility are non-negotiable. This file is authoritative for
the security model; it complements the control loop and safety invariants in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md),
the topology in
[app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md),
and the code/CI gates in
[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md).

## Severity Vocabulary

- **P0 blocker** — must be resolved and verified before any auto-execution is enabled; blocks
  promotion out of shadow mode.
- **P1** — required before a capability handles production (enforce mode) events.
- **P2** — hardening that may follow first enforce, tracked in Open Decisions with an owner.

## Execution Identity

This section governs the **non-human** executor identity. The **human** identity model —
who signs in to the console and ChatOps, what Entra groups exist, and how the console
delegates writes to a GitHub App — lives in
[user-rbac-and-identity.md](user-rbac-and-identity.md). Approval ≠ execution: humans
never hold the executor identity described below.

- The executor MUST authenticate through a **`WorkloadIdentity` interface** that exposes only
  "get a short-lived, audience-scoped OIDC token." This realizes the
  [Workload Identity contract](csp-neutrality.md#4-workload-identity-contract--oidc-token);
  concrete issuers (Managed Identity on Azure, IRSA on AWS, Workload Identity Federation on
  GCP, SPIFFE/SPIRE on any K8s) sit behind that interface, never in `core/`.
- On Azure the interface is backed by a **User-assigned Managed Identity**, scoped to an
  explicit **action whitelist**. No broad standing permissions.
- `DefaultAzureCredential()` (or any similarly named SDK entry point) is **prohibited in
  `core/`**; it appears only inside the Azure provider adapter behind the interface.
- **Per-vertical identity is the target end-state**, phased over the roadmap: Phase 1 ships
  a single `mi-aw-executor` (Change Safety only), Phase 3 splits into
  `mi-aw-change` / `mi-aw-dr` / `mi-aw-finops` when Resilience and Cost Governance land — see
  [Identity Mapping (Phased)](#identity-mapping-phased) below.
- Human approval identities (HIL) are distinct from execution identities; approval and
  execution are never the same principal, and no identity may assume another domain's identity
  (cross-domain assumption is denied, not just unused).
- Execution identities are **non-interactive**: no interactive/console sign-in, no human
  credentials attached, and disabled for any use outside the event loop.
- Prefer **credential-free auth**: workload identity federation / OIDC token exchange so the
  executor holds no long-lived secret. Where a secret is unavoidable it is short-lived and
  auto-rotated (see Secrets and Config).

### Identity Mapping (Phased)

Resolves P0 Open Decision *"Executor-side identity mapping"*. The plan is phased so Phase 1
does not carry unused per-domain infrastructure, but the interface (per-domain routing at
the risk-gate) is in place from day one so the Phase 3 split is a config change, not a
rewrite.

| Phase | MI(s) | Azure role strategy | Scope |
|-------|-------|---------------------|-------|
| **P1** (Change only) | 1 × `mi-aw-executor` | **Built-in role composition** — e.g. `Reader` + `Tag Contributor` + `Network Contributor` scoped to the Change action set. Each role assignment is enumerated in IaC. | **RG-scoped**, one assignment per governed resource group (fork Terraform iterates `for_each rg`). |
| **P2** (Custom Role transition) | 1 × `mi-aw-executor` | Derive a **Custom Role** whose `actions:` is the action whitelist observed in the Phase 1 shadow log — measurement-based least privilege, not theoretical. The Custom Role replaces the built-in composition in a governance PR. | RG-scoped (unchanged). |
| **P3** (Domain split) | 3 × `mi-aw-change`, `mi-aw-dr`, `mi-aw-finops` | Each MI gets its own Custom Role, derived the same way from that domain's shadow log. Cross-domain assumption is denied (matches the invariant above). | RG-scoped, per-domain scope sets. |

Rules that apply to every phase (MUST):

- **RG-scoped, never subscription-wide.** A new RG comes under governance only when the
  fork explicitly adds it to the assignment IaC — no automatic broadening.
- **Complementary Azure Policy `deny`** blocks any MI action outside its declared
  whitelist as a second line of defense, so a mis-assigned role cannot silently widen
  the surface.
- **Every action whitelist change is a governance PR** with `Justification:` and
  Owner-tier quorum on any change touching a Managed Identity role assignment
  ([user-rbac-and-identity.md](user-rbac-and-identity.md)).
- **Shadow log capture** is a Phase 1 deliverable: every action emitted by the
  executor MI in shadow mode records the exact Azure resource-provider operation it
  would call, so the Phase 2 Custom Role derivation is deterministic and auditable.

The Phase 3 split reuses the risk-gate's `Rule.domain` routing (already in the ontology
dispatch fields); no core code change is needed — the delivery layer selects the MI by
`Rule.domain` and the extra IaC provisions the new MIs.

## Authorization Model

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
  ([coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md)).
- **The app reads only environment variables (or K8s Secret mounts).** It MUST NOT call a CSP
  secret SDK (`SecretClient`, `SecretsManagerClient`, `SecretManagerServiceClient`, …); this
  realizes the [Secret contract](csp-neutrality.md#3-secret-contract--environment--k8s-secret).
  On Azure the injection layer is **Container Apps native secret + Key Vault reference**; on
  Kubernetes it is **External Secrets Operator** with a `SecretStore` CRD.
- Access secrets through an injected `SecretProvider` in `shared/providers/`, never a global
  read at import.
- **Lifecycle**: every secret has an owner, a defined rotation interval, and automated rotation;
  compromised or superseded material is revoked immediately. Prefer federated tokens so there
  is no secret to rotate.
- **Fail-closed**: if the secret injection layer or token issuer is unavailable at startup, the
  process fails fast — it does not fall back to a cached or embedded credential and never
  starts in a degraded state.
- Secrets MUST NOT appear in logs, audit entries, error messages, test fixtures, or LLM prompts.
- Keep the repo customer-agnostic
  ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## Data Protection

- **Classify** data handled by the control plane (event payloads, tool output, audit records,
  embeddings) and minimize it: store pointers/ids, not raw customer bytes or PII.
- Encrypt in transit (TLS) and at rest; keys are managed in the secret/key store, not in code.
- **LLM data handling**: T2 prompts are redacted of secrets and PII before leaving the trust
  boundary; enforce data-residency and no-retention terms for any external model vendor. A
  prompt that would require unredactable sensitive data is routed to HIL instead of sent.

## Network Boundaries

- The executor and core engine have **no public inbound endpoint**; ingress is the event bus
  only. Management/API surfaces sit behind private networking.
- **Egress is allow-listed** to required cloud control planes and model endpoints; default-deny
  outbound to contain exfiltration and injection-driven callbacks.
- Layer identities are not shared across the network boundary; the read-only console and
  ChatOps never hold the executor identity
  ([app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)).

## Supply-Chain Integrity

- Dependencies are pinned via lockfile; CI installs from the lockfile only and a vulnerability
  scan blocks high-severity findings.
- The rule catalog and IaC are catalog-as-code behind **protected branches with signed
  commits/PR review**; no direct pushes to the enforce branch.
- Build artifacts (container images) are signed and their provenance/SBOM recorded; the
  executor pulls only verified, pinned digests, never mutable `latest` tags.

## Safety Invariants (every autonomous action)

1. **Stop-condition** — a defined halt state that aborts the action.
2. **Rollback path** — a tested way to revert (git revert for PR-native actions; an equivalent
   scripted/IaC revert for any non-PR action, which must still supply rollback and audit).
3. **Blast-radius limit** — scope caps (non-prod first, batch size, rate) plus per-resource
   serialization so concurrent actions on one resource are mutually excluded.
4. **Audit-log entry** — append-only record of who/what/why/when and the outcome.

Missing any of the four = the action is incomplete and must not ship. Each invariant is
**testable**: shadow-mode tests prove no mutation, rollback tests prove prior state is restored,
and property-based tests assert "high-risk never auto-executes" and "re-applying an action is a
no-op".

## Rate Limiting and Kill-Switch (DoS and containment)

- The event loop and executor enforce **rate/budget caps** (per-tier, per-resource, and global);
  exceeding a cap degrades to HIL, never to ungated auto-action. This also bounds cost and a
  runaway or event-flood (DoS) condition.
- A **global kill-switch** halts all auto-execution immediately and drops every path to
  shadow/HIL; it is operable without the executor identity.
- A **break-glass** procedure grants scoped emergency access under mandatory audit and
  post-incident review; break-glass use raises an alert and auto-expires.

## Shadow → Enforce Promotion

- New capabilities ship in **shadow mode**: judge and log only, no execution.
- Promotion to enforce is explicit, per-action, and gated on a **minimum shadow duration and
  sample size**, measured accuracy above threshold, and **zero policy-violation escapes** in
  shadow (metrics defined in [goals-and-metrics.md](goals-and-metrics.md)).
- Regressions demote back to shadow automatically; every promotion and demotion writes an
  audit entry.

## HIL Approval Integrity

- Approval and execution are distinct principals; **no self-approval**, and high-blast-radius
  actions require **quorum (multi-approver)** rather than a single approver.
- Approvers authenticate with MFA/phishing-resistant credentials; each approval is bound to a
  specific action + idempotency key so it **cannot be replayed** against a different action.
- **Timeout is fail-closed**: an unapproved HIL item on timeout or reject results in a no-op
  plus an audit entry, never a default-execute.

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

## Threat Model (STRIDE)

Event payloads and tool output are **untrusted**; the deterministic verifier and policy
re-check are the authority, never model or event text.

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
| ~~P0~~ | ~~Executor-side identity mapping~~ — **resolved** in [Identity Mapping (Phased)](#identity-mapping-phased) | — | — |
| ~~P0~~ | ~~Risk-classification policy (auto vs HIL) and initial policy approver~~ — **resolved** in [risk-classification.md](risk-classification.md) | — | — |
| P1 | Policy-exemption workflow owner and SLA | TBD | before production |
| P1 | Audit tamper-evidence scheme (hash-chain + anchoring cadence) | TBD | before production |
| P1 | Kill-switch and break-glass runbook and drill schedule | TBD | before production |
| P2 | Compliance control mapping (MCSB / CIS / SOC 2) and evidence collection | TBD | post first enforce |
| P2 | Secret rotation intervals and federation coverage per identity | TBD | post first enforce |
