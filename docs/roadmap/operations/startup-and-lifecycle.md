---
title: Startup and Lifecycle
---
# Startup and Lifecycle

How FDAI **starts from cold and reaches steady state** on a freshly provisioned Azure
subscription. Answers: when does the system "start"? What is in the catalog on day zero?
When does the autonomous discovery loop begin? How is the shadow → enforce lifecycle
sequenced?

Complements [deploy-and-onboard.md](../deployment/deploy-and-onboard.md) (which handles provisioning) and
[operating-and-verification.md](operating-and-verification.md) (which handles ongoing
observation). Design invariants come from
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

Azure focus: non-Azure providers are TBD (see
[Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).
Timeline suggestions below are directional, not hard rules; **the gates are hard**.

## Cold Start (scale-to-zero specifics)

The core engine runs on Container Apps with **KEDA scale-to-zero** and event-driven scaling.
The core is a **single Container App with sidecar containers** (`event-ingest` primary,
`trust-router` / `executor` / `audit-writer` as sidecars - see
[deploy-and-onboard.md](../deployment/deploy-and-onboard.md#compute-shape-sidecar-containers)). "Starting"
therefore means:

1. At least one event arrives on the ingress.
2. KEDA scales the app's replica set from zero; **all sidecars come up together** (one scale
   unit).
3. The primary container loads config, opens state / audit / event-bus connections, hydrates
   the rule catalog into OPA; sidecars complete their own boot in parallel and expose
   readiness on `localhost`.
4. The event flows through `event-ingest → correlation → trust-router → tier → risk-gate →
   audit`, hopping between sidecars over `localhost` IPC.

Rules that apply to every cold start:

- **Cold-start metric**: the first event on a cold path MAY exceed the T0 latency budget while
  the replica warms. This latency MUST be recorded as a separate **cold-start metric** so the
  T0 warm latency percentile is not polluted. Cold vs warm are reported side by side in the
  KPI dashboard ([goals-and-metrics.md](../architecture/goals-and-metrics.md)).
- **Cold-start deadline**: exceeding a configured deadline degrades the event to HIL, never
  to an ungated auto-action ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- **Cold-start ordering**: cold-started replicas MUST respect the per-resource ordering /
  idempotency guarantees; a replica coming up cannot violate the "same event twice = one
  effect" invariant.
- **Sidecar readiness gating**: the primary container MUST NOT accept an event until every
  sidecar's readiness probe is green; otherwise a partial cold start could route an event
  into a sidecar that has not opened its dependencies.

**TBD**: the concrete cold-start deadline and the exact cold-start-metric name / definition.

## Initial Rule Catalog State

The upstream repo ships **no customer-specific rules**. On day zero of a fork's deployment
the catalog is populated from two sources - in order:

1. **Bootstrap seed set** (fork responsibility) - an initial catalog snapshot, pinned by
   `content_hash` and version, that the fork commits to its own catalog-as-code repo.
2. **Autonomous collectors** (upstream) - after the first successful collector run, upstream
   sources are ingested at their configured cadence per
   [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md).

Rules that apply to the day-zero catalog:

- Every rule MUST default to **`effect: audit` (shadow)** regardless of severity. There is no
  way to ship a rule that starts in enforce; a rule that would land in enforce on day zero
  fails the promotion gate ([rule-governance.md](../rules-and-detection/rule-governance.md)).
- Every rule MUST carry grounded **`provenance`** (source URL + resolved revision + content
  hash + license + `redistribution` flag), including seed rules. A rule without provenance
  fails schema validation.
- **No LLM-generated candidate** enters the catalog before the autonomous discovery loop has
  been enabled and its quality gate is available.

**TBD**: which sources ship in the day-zero seed set and their exact rule ids - this is the
same open item as Phase 1's "initial target set enumerated per source"
([phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md)).

## Event Source Bootstrap

Before any event can be judged, ingress must be attached to Azure signals:

1. **Diagnostic Settings** - on the target subscription and each in-scope resource group,
   enable Diagnostic Settings that forward Activity Log (and any resource-specific logs) into
   an **Event Hubs Kafka topic** - this is the CSP-neutral event bus contract
   ([csp-neutrality.md § Event bus contract](../architecture/csp-neutrality.md#1-event-bus-contract--kafka-wire-protocol)).
2. **Kafka topics + consumer groups** - create the day-zero topics on the Event Hubs
   namespace (`aw.change.events`, `aw.dr.events`, `aw.finops.events`, and their `<topic>.dlq`
   siblings) and register the consumer group for `event-ingest`.
3. **Idempotency prime** - the event-ingest layer stamps an **idempotency key** on every
   incoming event on first receipt so a replay is a no-op end to end.
4. **DLQ verified reachable** - dead-letter destinations (Kafka `<topic>.dlq`) are exercised
   (poison-pill probe) before enforce is enabled anywhere.

Concrete event types and filter expressions are **TBD** and captured in
[deploy-and-onboard.md#event-source-subscription](../deployment/deploy-and-onboard.md#event-source-subscription).

## Model Provisioning Bootstrap

Before T2 can run, the capability→deployment mapping must be resolved. The deployment pipeline
runs the resolver before `terraform apply`; this is not a manual runtime step:

1. **Resolver runs from `rule-catalog/llm-registry.yaml`** - reads preferences per
   capability, queries the Azure OpenAI / Foundry catalog for the target region, and
   provisions one deployment per capability with its `capacity_tpm` cap.
2. **Mixed-model invariant verified** - `t2.reasoner.primary.publisher` MUST differ from
   `t2.reasoner.secondary.publisher`, or the bootstrap aborts (no silent same-vendor
   fallback). Fork's `llm.mixed_model_mode` (`azure-foundry` / `external` / `hil-only`)
   selects the strategy.
3. **`resolved-models.json` written to Key Vault** - capability → `{deployment, family,
   version, publisher}`. Every subsequent audit entry names the exact model that decided
   the case.
4. **Weekly reconciler follows as a deferred increment** - until W-I in
   [dev-and-deploy-parity.md](../deployment/dev-and-deploy-parity.md) lands, model changes are
   reviewed through an explicit registry PR. The reconciler will watch for newer families and
   deprecation notices and open draft PRs; it will never auto-swap the live mapping.

Full design: [llm-strategy.md § Model Provisioning and Lifecycle](../architecture/llm-strategy.md#model-provisioning-and-lifecycle).

## Shadow-First Rollout Recipe

Every new deployment lands in **shadow-only mode** for its entire footprint. Promotion is
per-action, per-rule, per-domain - never a global flip. Suggested milestones (all timelines
are **directional**; the gates are hard):

| Milestone | Focus | Gate to advance |
|-----------|-------|-----------------|
| **D+0 → D+7** | verify the loop runs end-to-end in shadow: events land → tier decides → audit records | zero silent drops, zero unauthenticated actions, canary green |
| **D+7 → D+14** | measure per-rule shadow accuracy + false-positive rate; identify low-risk promotion candidates | shadow sample size and accuracy threshold per [goals-and-metrics.md](../architecture/goals-and-metrics.md) |
| **D+14 → D+30** | promote a small first batch of low-risk rules to `remediate` (PR-only), HIL for anything ambiguous | zero policy-violation escapes in the shadow window |
| **D+30 →** | continuous promotion cycle, one rule at a time, each per the enforce-promotion approval gate | regression suite green, measured accuracy stable |

Rules that apply throughout:

- Any regression **auto-demotes** the promoted rule back to shadow - demotion never requires
  the promotion approver, so degradation to safety is always fast
  ([rule-governance.md](../rules-and-detection/rule-governance.md#effects-mode)).
- Enforce promotion requires a **separate approval** from the operator who proposed it
  ([security-and-identity.md](../architecture/security-and-identity.md)).
- The kill-switch is verified reachable before D+7 ends.

## HIL Approver Bootstrap

Before any enforce-mode rule can be promoted, the approver group MUST be provisioned. If no
approver exists, high-risk findings queue and alert via the fallback channel; **they never
auto-execute**. The Entra group model is defined in
[user-rbac-and-identity.md](../interfaces/user-rbac-and-identity.md).

Steps (fork responsibility):

1. Create the Teams **group-connected team** backed by `aw-approvers` for HIL A1 traffic
   and digests; membership then follows the Entra group automatically
   ([channels-and-notifications.md#51-audience-derivation-channel-as-audience](../interfaces/channels-and-notifications.md#51-audience-derivation-channel-as-audience)).
2. Provision the five Entra security groups (`aw-readers`, `aw-contributors`, `aw-approvers`,
   `aw-owners`, `aw-break-glass`) and inject their objectIds into the config slots
   ([user-rbac-and-identity.md#42-security-groups-slots](../interfaces/user-rbac-and-identity.md#42-security-groups-slots)).
3. Apply Conditional Access to `aw-approvers`/`aw-owners`: phishing-resistant MFA required,
   legacy auth blocked; add compliant-device on `aw-owners`
   ([user-rbac-and-identity.md#43-conditional-access](../interfaces/user-rbac-and-identity.md#43-conditional-access)).
4. Populate `aw-approvers` with at least the number of members needed to sustain the
   **quorum-2** rule for enforce promotions, exemptions, and overrides
   ([user-rbac-and-identity.md#51-codeowners-single-approver-group-path-based-reviewer-count](../interfaces/user-rbac-and-identity.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
5. Register the approver group id in the executor's Chat adapter config so Adaptive Card
   approvals can validate role claims.
6. **Provision the Slack workspace** (P1 A1 channel): install the FDAI Slack app,
   grant `chat:write`, populate the mandatory Slack userId ↔ Entra OID mapping store; the
   Slack adapter refuses A1 traffic until the mapping is non-empty
   ([channels-and-notifications.md#7-channel-specific-notes](../interfaces/channels-and-notifications.md#7-channel-specific-notes)).
7. Commit `rule-catalog/channel-routing/` config (primary/fallback channels, digest
   schedule, audience) with the same review rigor as rules; Owner-tier reviewers are
   required for any change touching A1 routing.
8. Run a **dry-run HIL** through the canary path to confirm approvals land, `justification`
   is required, timeout is fail-closed, and every approval writes an audit entry with a
   `correlation_id`.

## Autonomous Discovery Loop Kickoff

The [autonomous rule discovery loop](../rules-and-detection/rule-catalog-collection.md#autonomous-rule-discovery) is
**disabled on day zero**. It MUST NOT run before all of the following:

1. The audit log has accumulated at least **`N` shadow decisions**, giving the observe stage a
   real baseline. `N` is configurable; **TBD** - recommended in the low thousands.
2. At least one collector has run to success (proves the wire-up + provenance).
3. The mixed-model cross-check target and the deterministic verifier are healthy.
4. Post-deploy smoke tests are green
   ([operating-and-verification.md](operating-and-verification.md#post-deploy-smoke-tests)).

Once enabled, the loop runs on a configured cadence. A candidate rule from the loop is inert
until it passes the full quality gate - the loop cannot mutate the catalog directly.

Disabling the loop is a **policy toggle**, not a code change; recurring override signals still
accumulate on the audit log for the next enable.

## Lifecycle States

Every artifact progresses through defined, auditable states. Transitions are the only way to
move between them; each transition is versioned and audited.

- **Rule / rule-set** - `draft → audit(shadow) ⇄ enforce(deny/remediate) → deprecated`, with
  `disabled` reachable from any active state
  ([rule-governance.md#lifecycle-and-versioning](../rules-and-detection/rule-governance.md#lifecycle-and-versioning)).
- **Assignment** - bound to a scope, an `effect`, and an `enforcement` flag. Effects
  transition under the promotion gate; regressions auto-demote.
- **Exemption** - `active → expired` (time-boxed; no auto-renew)
  ([rule-governance.md#exemptions](../rules-and-detection/rule-governance.md#exemptions)).
- **Override** - `active → removed`; may be long-lived (no forced expiry), scope MUST be
  resource-group-equivalent or narrower
  ([rule-governance.md#overrides](../rules-and-detection/rule-governance.md#overrides)).
- **Action** - `proposed → risk-gated → executed | rejected → rolled-back (if applicable)`.
  Every state carries the idempotency key so a replay is a no-op.

## Open Decisions

- [ ] Cold-start deadline value and the exact cold-start-metric name.
- [ ] Day-zero seed rule set (which sources, which rule ids) - cross-linked to Phase 1.
- [ ] Discovery-loop kickoff threshold `N` (shadow-decision count) and its regression-safety
      rationale.
- [ ] Kafka topic layout + Diagnostic-Settings forwarder filter shape and per-source rate caps.
- [ ] Bootstrap runbook: the exact command sequence for a fork to reach D+0 (owned by
      [operating-and-verification.md](operating-and-verification.md#runbook-set)).
- [ ] Dry-run HIL procedure: canary payload, expected timing, teardown.
