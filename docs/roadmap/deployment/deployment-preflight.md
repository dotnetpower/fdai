---
title: Deployment Preflight (feasibility and blocker collection)
---
# Deployment Preflight (feasibility and blocker collection)

Before a deployment runs (`terraform apply`, or a control-plane remediation PR),
the **deploy-preflight** pass collects everything in the target environment that
could block or degrade the deployment, grounds each item in the exact rule that
produced it, and maps it to the concrete lever that clears it. It is the
[what-if verifier](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
generalized from a single action to a whole deployment.

This resolves a recurring class of failures - a plan that is correct in isolation
but is rejected by the target subscription's guardrails: a denied resource type,
a blocked package or image source, a missing role assignment, an exhausted quota,
or a dependency that must exist before the resource it supports. Instead of
discovering these one at a time as `terraform apply` fails, the preflight pass
reports them all at once, up front.

> Customer-agnostic: every denylist, blocked host, mirror endpoint, and toggle
> value below is supplied by config or a fork - the upstream ships the machinery
> and generic taxonomy, never a customer's specific guardrail values
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Probe contracts, deterministic probes, analyzer, and report | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/`, `services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py`, and focused deploy-preflight tests | Stable findings, fail-closed probe execution, verdicts, and shadow-versus-enforce behavior are tested. |
| Read-only Azure probes and protected-plan evidence | implemented | `scripts/deployment/azure/run_live_preflight.py`, `.github/workflows/deploy-dev.yml`, and `tests/integration/scripts/test_run_live_preflight.py` | The protected runner invokes the standalone script, requires all four live categories, sanitizes evidence, and binds its digest to the plan. |
| Terraform toggle, alternate-rendering fixture, and environment-profile primitives | implemented | `infra/modules/preflight-toggles/`; focused `terraform test -filter=tests/alternate_rendering.tftest.hcl`, `test_environment_profile.py`, and `test_reassembly_proposals.py` checks | The generic upstream root intentionally does not instantiate the fork-owned resource consumer. The durable profile refresh task is not composed. |
| Check publishing and sanitized GitHub adapter | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/check_publish.py`, `services/core-control-plane/src/fdai/delivery/github/preflight_checks.py`, and focused tests | The adapter posts a bounded status on an existing PR head without exposing scope, findings, evidence, or metadata. It is not yet bound to a live PR flow. |
| Pre-publication verification gate | implemented | `services/core-control-plane/src/fdai/core/deploy_preflight/pre_publication_gate.py` and `test_pre_publication_gate.py` | The analyzer runs again before any remediation proposal is submitted; a blocking, stale, or scope-changed report withholds publication and submits nothing. |
| PR delivery refresh wrapper | implemented | `services/core-control-plane/src/fdai/delivery/deploy_preflight/pr_publication.py` and `services/core-control-plane/tests/delivery/test_preflight_pr_publication.py` | An injected read-only refresh must bind the exact patch digest, trusted scope, complete probe categories, and current non-blocking report before the existing PR publisher is called. |
| Control-loop pre-PR gate and GitHub delivery composition | in-progress | The deterministic gate and delivery adapters above | No live trigger or runtime binding supplies the exact-plan refresh, and no live path invokes the wrapper or posts a GitHub Check. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected the protected-runner path to the current standalone preflight entrypoint. | current change; focused core preflight and live-script checks listed in the scope table | Compose the root toggle consumer, durable profile refresh, GitHub publisher, and control-loop gate. |
| 2026-08-24 | implemented | Resolved the root-consumer ownership conflict by keeping concrete resource rendering fork-owned and adding a reusable mock-provider plan fixture for the upstream disk toggle contract. | `current change`; `infra/modules/preflight-toggles/reference-disk-consumer/tests/alternate_rendering.tftest.hcl`; focused Terraform test passed 2 cases. | Each fork binds the validated pattern in its owned compute module. The durable profile refresh, GitHub publisher, and control-loop gate remain open. |
| 2026-09-26 | in-progress | Added the deterministic pre-publication gate: the analyzer is re-run on the accumulated overrides before any remediation proposal is submitted, and a blocking, stale, scope-changed, or escalated pass is lowered to human review with nothing submitted. | `current change`; `services/core-control-plane/src/fdai/core/deploy_preflight/pre_publication_gate.py`; `uv run pytest tests/core/deploy_preflight -q` passed 98 tests. | Compose the gate on the live control-loop path, add the durable profile refresh, and add the GitHub Checks publisher. |
| 2026-09-26 | in-progress | Hardened the gate after review: a padded expected scope is normalized, a non-finite freshness window and a naive clock are rejected before any submission, and a hold record retains a bounded set of finding ids. | `current change`; `services/core-control-plane/tests/core/deploy_preflight/test_pre_publication_gate.py`; focused `uv run pytest tests/core/deploy_preflight -q` passed. | Unchanged: compose the gate on the live control-loop path, add the durable profile refresh, and add the GitHub Checks publisher. |
| 2026-09-26 | in-progress | Closed the verdict coverage gap found in review: a warning-only report and a clean shadow report both publish a shadow-first proposal, and both paths are now asserted. | `current change`; `services/core-control-plane/tests/core/deploy_preflight/test_pre_publication_gate.py`; focused `uv run pytest tests/core/deploy_preflight -q` passed 105 tests. | Unchanged: compose the gate on the live control-loop path, add the durable profile refresh, and add the GitHub Checks publisher. |
| 2026-09-26 | in-progress | Added a delivery-side pre-PR refresh wrapper and sanitized GitHub Checks adapter using existing provider seams, without granting either execution or approval authority. | `current change`; `services/core-control-plane/src/fdai/delivery/deploy_preflight/pr_publication.py`, `services/core-control-plane/src/fdai/delivery/github/preflight_checks.py`, and focused delivery tests (`uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_preflight_pr_publication.py services/core-control-plane/tests/delivery/test_github_preflight_checks.py`, 30 passed). | Compose a trusted live refresh and fence source-base drift, bind Checks after PR creation, carry governed toggle arguments, and add durable profile invalidation and operational evidence. |

### Remaining work

- [x] Keep the generic upstream root free of fork-owned resource consumers and ship a reusable
  Terraform fixture proving that `attach_existing` removes the policy-denied managed-disk shape
  from the alternate plan. The focused fixture passes both renderings.
- [ ] Add a durable environment-profile refresh task with Inventory-delta invalidation and pass restart and expiry tests.
- [x] Invoke the analyzer again before remediation-PR publication and lower a blocking, stale, or
  scope-changed report to human review. `core/deploy_preflight/pre_publication_gate.py` and
  `tests/core/deploy_preflight/test_pre_publication_gate.py` prove that a withheld pass submits no
  proposal, so no PR opens on a blocked report.
- [ ] Compose that gate on the live control-loop path so the executor's remediation PR is published only behind it, and retain the composed run evidence.
- [x] Add a PR-publisher wrapper that withholds delivery on unavailable refresh, patch or scope drift,
  stale or incomplete evidence, or blocking findings, and prove no GitOps HTTP call occurs on a hold.
- [x] Add a sanitized GitHub Checks adapter for an existing PR head with focused redaction,
  advisory shadow, idempotency, and unavailable-delivery tests.
- [ ] Bind the PR refresh and Checks adapter to the live runtime using a trusted scope and
  re-render/re-plan callback; fence source-base drift between refresh and provider commit, carry
  per-toggle arguments through governed ingress, and record a composed run with fresh report
  and exact head revision.

## Where It Sits in the Loop

The design defines two entry points that share one analyzer. The protected human deploy path is
shipped through a standalone runner script; the control-plane path currently stops at the seam:

- **Control plane (partly shipped)**: before the [executor](../architecture/project-structure.md) emits a
  remediation PR, the analyzer checks that the change would actually land in the
  target scope. A blocking finding degrades the action to `hil` rather than
  opening a PR that would fail policy. The deterministic gate that enforces this
  ordering and a delivery wrapper for exact-patch refresh exist and are tested;
  no live path binds the required refresh yet.
- **Human deploy (shipped)**: the private-runner workflow creates the report before plan
  and binds its evidence digest into exact-plan metadata. PR comment/GitHub Check delivery
  remains a follow-up.

Both paths are **deterministic-first** (T0-flavored): static analysis with no
cloud calls resolves most findings; bounded, read-only live probes confirm the
rest (egress reachability, quota). Nothing in the pass mutates anything.

## Probe Taxonomy

A *probe* inspects a `PreflightTarget` (the scope plus the resource types, egress
hosts, and required links a deployment intends to touch) and returns grounded
findings in one category. The generic catalog:

| Category | Representative blocker | Detection (deterministic-first) |
|----------|------------------------|---------------------------------|
| `policy_guardrail` | disallowed resource types, NSG required, inline disk denied, public IP denied | `terraform plan` JSON re-checked against `policies/` (OPA) + Azure Policy deny simulation (static) |
| `supply_chain_egress` | `docker.io` blocked, PyPI / npm / apt blocked, external base image pull denied | NSG / Firewall / UDR rule analysis (static) + bounded egress reachability probe (live) |
| `identity_rbac` | executor identity lacks a role on the target scope; cannot create a role assignment | scope role-assignment check from the inventory graph (static) |
| `quota_capacity` | SKU / region quota exceeded, zone capacity unavailable | quota lookup (live, cached) |
| `dependency_ordering` | disk before VM, NSG before subnet, private endpoint before resource | ordering violation derived from policy + the module dependency graph (static) |
| `secret_config` | Key Vault reference unresolvable, required secret absent | secret existence / reachability check (static) |

The `policy_guardrail` and `supply_chain_egress` categories are the two the
hardened-network customers hit most: they map directly to the Azure Policy
`deny` guardrails (`Not allowed resource types` / `Allowed resource types`) and
to firewall egress denylists. See
[rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md) for how the underlying
rules are sourced.

## Readiness Report

Findings are assembled into one `DeploymentReadinessReport`
([core/deploy_preflight/report.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/report.py)).
Each finding carries three required parts:

- **evidence** - a CSP-neutral citation of the rule that produced it
  (`policy:<neutral-id>`, `nsg:<neutral-id>/rule:<name>`). A probe that cannot
  cite a source MUST NOT emit a finding; an ungrounded blocker is a defect, the
  same rule the T2 verifier follows.
- **severity** - `blocking` (gates an enforce-mode deploy) or `warning`
  (surfaces but never gates).
- **resolution** - how to clear it, mapped to a concrete lever when possible
  (see the toggle table below).

### Decision Semantics

| Verdict | Meaning |
|---------|---------|
| `clear` | no findings |
| `needs_review` | findings exist but none is blocking (warnings only) |
| `blocked` | at least one blocking finding |

The report always records the **truthful** verdict. Whether that verdict *gates*
a deploy is a separate flag, `blocks_deploy`, which is true only when the pass
ran in `enforce` mode.

### Shadow-First

Every new probe ships in **shadow mode**: it reports blockers truthfully but
`blocks_deploy` stays `false`, so an unproven probe can never wrongly stop a
human deploy on a false positive. A probe is promoted to `enforce` per-category
only after its false-positive rate is measured on the frozen scenario set - the
same promotion discipline the [ActionType contract](../architecture/llm-strategy.md) applies to
autonomous actions.

### Publication Holds

A cleared reassembly is a decision taken at some earlier moment. Before any
remediation proposal is submitted, the gate re-runs the same analyzer on the
accumulated overrides and withholds publication whenever the fresh report cannot
justify it:

| Hold | Cause |
|------|-------|
| `no_applied_toggle` | the loop applied no toggle; the pass is a no-op rather than a rejection |
| `reassembly_escalated` | the loop escalated; a partial reassembly is never submitted |
| `blocking_finding` | the re-verified report still carries a blocking finding |
| `stale_evidence` | the report is outside the freshness window or its timestamp is unusable |
| `scope_drift` | the report or an applied toggle does not bind the expected scope |

Every hold is decided before the first submission, so a withheld pass submits
nothing rather than a partial proposal set, and the truthful verdict gates
publication even in shadow mode where `blocks_deploy` stays false. A verifier
that raises propagates before any submission; the caller routes the pass to
`hil`.

For the PR delivery seam, a separate wrapper re-runs a caller-provided read-only
plan refresh on every publish attempt, including redelivery. It requires the
verified patch SHA-256 to equal the immutable proposed patch, the report scope
to equal the caller's trusted scope, and all required probe categories to be
checked. Missing refresh, changed patch, incomplete coverage, stale evidence,
or a blocker withholds the PR even in shadow mode. The wrapper cannot prove a
provider re-probed by checking a timestamp alone: the caller still owes an
authoritative re-render and read-only reanalysis after source or Inventory
changes. The current PR publisher does not yet bind the refresh to its
subsequent base-branch resolution, so a source change between those operations
remains a live-composition blocker. An unbound wrapper is not a production gate.

The GitHub Checks adapter can annotate an **existing** PR's exact head revision.
It exposes only mode, decision, capped finding count, and checked-category
count; raw scope, evidence, finding text, and caller metadata stay private.
Shadow reports are advisory. A missing adapter or failed Check does not certify
preflight and cannot undo an already opened PR. GitHub does not offer an
atomic create-if-absent Check call across processes; live composition needs
single-writer delivery or a durable lock before claiming distributed
idempotency.

## Blocker to Terraform Toggle Mapping

A report is not just a list of problems; each `terraform_toggle` finding names
the infra sub-module and variable override that makes the deployment comply.
This reuses the existing `infra/modules/<seam>/` + `var.<seam>_kind` selection
pattern ([project-structure.md](../architecture/project-structure.md)), generalized to
resource-provisioning modes so the module output contract stays fixed while its
internal wiring switches:

| Toggle | Values | Effect |
|--------|--------|--------|
| `disk_provisioning` | `inline` \| `attach_existing` | create the VM disk inline vs attach a pre-provisioned disk (`var.existing_disk_ids`) |
| `nsg_provisioning` | `create` \| `byo` | create an NSG vs reference an existing one (`var.existing_nsg_id`), attached as the guardrail requires |
| `registry_source` | `docker_io` \| `acr_mirror` | pull base images from an internal registry mirror instead of `docker.io` |
| `python_index_url` | (string) | point package installs at an internal PyPI mirror / artifact feed |
| `dependency_ordering` | `strict` | split prerequisite resources (disk, NSG, private endpoint) into an ordered apply stage |

The mapping is what makes a denied resource type a non-problem: an inline-disk
deny resolves to `disk_provisioning=attach_existing`, so the plan never emits the
denied operation in the first place. When a resolution is marked `autofix`, the
analyzer may propose the toggle change as a remediation PR without human
judgment; otherwise it emits guidance and routes to review.

## Subsystem Layout

| Piece | Location | Role |
|-------|----------|------|
| Probe seam | [shared/providers/feasibility_probe.py](../../../services/core-control-plane/src/fdai/shared/providers/feasibility_probe.py) | `FeasibilityProbe` Protocol + finding / target dataclasses |
| Generic probes | [shared/providers/local/feasibility.py](../../../services/core-control-plane/src/fdai/shared/providers/local/feasibility.py) | deterministic, config-driven upstream defaults (no network) |
| Orchestrator | [core/deploy_preflight/analyzer.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/analyzer.py) | fan out over probes, assemble the report (fail-closed) |
| Report | [core/deploy_preflight/report.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/report.py) | the assembled artifact + verdict + `blocks_deploy` |
| Pre-publication gate | [core/deploy_preflight/pre_publication_gate.py](../../../services/core-control-plane/src/fdai/core/deploy_preflight/pre_publication_gate.py) | re-verify before proposal submission; withhold and route to human review |
| PR delivery wrapper | [delivery/deploy_preflight/pr_publication.py](../../../services/core-control-plane/src/fdai/delivery/deploy_preflight/pr_publication.py) | require an exact-patch refresh before the injected PR publisher |
| GitHub Checks adapter | [delivery/github/preflight_checks.py](../../../services/core-control-plane/src/fdai/delivery/github/preflight_checks.py) | post a bounded status to an existing PR head, without approval authority |

`core/` sees only the `FeasibilityProbe` Protocol; the probes are injected at the
[composition root](../../../services/core-control-plane/src/fdai/composition/__init__.py) via the
`Container.feasibility_probes` seam. The upstream default binds no probes (the
denylists are customer config); a fork or a live Azure adapter registers its own
without editing `core/`.

## Safety Posture

- **Fail-closed** - a probe that raises propagates; the pass never reports
  `clear` on a partial run. A blocking finding degrades a control-plane action to
  `hil`, never to an ungated auto-action.
- **Read-only** - probes never mutate; the pass is safe to run on every deploy.
- **Idempotent** - findings are ordered deterministically (blocking first, then
  by id), so a re-run over the same inputs produces a byte-identical report.
- **Grounded** - no finding without evidence citing its source rule.
- **Discovery feedback** - recurring blockers across environments (for example,
  every scope blocks `docker.io`) are a signal to the discovery loop to propose a
  new default toggle or rule
  ([architecture.instructions.md § Rule Catalog](../../../.github/instructions/architecture.instructions.md#rule-catalog)).

## Delivery Status

Shipped: the probe seam, generic deterministic probes, analyzer + report, standalone Azure
preflight script, protected-plan evidence binding in the deploy workflow, and tests.

1. **Azure probes and protected-plan evidence (shipped)**: a shared read-only ARM client (`AzureArmClient`, injected
   `httpx.AsyncClient` + `WorkloadIdentity` bearer token, fail-closed) plus the
   `AzurePolicyGuardrailProbe` (real Azure Policy `deny` guardrails - `Not
   allowed` / `Allowed resource types`) and the `AzureQuotaProbe` (Compute
  usages per subscription + location) have landed with mock-HTTP unit tests. The policy parser
  accepts the built-in `allOf` type constraint only when every sibling is the canonical
  type-exists guard; unknown siblings remain fail-closed. Isolated live validation proved one
  RG-scoped disk deny maps to `disk_provisioning=attach_existing`, while a real quota shortage
  remains a manual blocker; the temporary assignment was removed through its reviewed rollback.
  `scripts/deployment/azure/run_live_preflight.py` composes them through the same
  analyzer with Azure CLI workload identity, bounded read-only ARM transport,
  neutral-to-ARM type mapping, and sanitized fail-closed errors. The existing
  Resource Graph role observer is also composed through `AzureIdentityRbacProbe`
  to report missing event-bus and secret-reader executor roles without emitting
  principal or role-definition ids. `AzureSecretConfigProbe` checks required Key
  Vault references by status only, never reads a response body or secret value,
  and emits hashed references. Reports record sanitized per-category check coverage even when
  clear. The private runner requires all four Azure categories in enforce mode, combines them with
  bounded TLS egress evidence, stores only sanitized reports in private Blob storage, and binds
  both evidence digests into exact-plan verification. The Firewall / NSG topology adapter remains
  a separate future enhancement; it is not required for direct runner reachability evidence.
  2. **Capability-mode toggle scaffold (shipped)**: `infra/modules/preflight-toggles/` and the
    disk reference consumer validate both renderings. The generic upstream root does not
    instantiate the concrete consumer because resource ownership and integration stay fork-owned.
  3. **Check-publishing seam (partly shipped)**: the core function, provider Protocol,
    in-memory publisher, and sanitized GitHub Checks adapter exist. Runtime binding
    after infrastructure-PR creation remains planned.
  4. **Deployment Environment Profile primitive (shipped)**: bounded in-memory cache, TTL,
    and Inventory-delta invalidation helper exist. The composition refresh task and durable
    cache wiring are planned.
  5. **Control-loop pre-PR gate (partly shipped)**: `pre_publication_gate.py` re-runs the same
    analyzer on the accumulated overrides immediately before publication and withholds every
    unproven case - a blocking finding, stale evidence, a scope change, or an escalated
    reassembly - so the pass routes to `hil` and submits nothing. The PR delivery wrapper
    also holds on invalidated exact-patch evidence, but neither is bound to a live executor
    path yet.

## References

- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) - control loop, quality gate, safety invariants
- [project-structure.md](../architecture/project-structure.md) - module boundaries, infra sub-module pattern
- [risk-classification.md](../decisioning/risk-classification.md) - how a blocking finding routes to `hil`
- [rule-catalog-collection.md](../rules-and-detection/rule-catalog-collection.md) - where the underlying guardrail rules come from
