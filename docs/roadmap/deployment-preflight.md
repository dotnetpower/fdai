---
title: Deployment Preflight (feasibility and blocker collection)
---
# Deployment Preflight (feasibility and blocker collection)

Before a deployment runs (`terraform apply`, or a control-plane remediation PR),
the **deploy-preflight** pass collects everything in the target environment that
could block or degrade the deployment, grounds each item in the exact rule that
produced it, and maps it to the concrete lever that clears it. It is the
[what-if verifier](../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
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
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## Where It Sits in the Loop

The pass runs at two entry points, sharing one analyzer:

- **Control plane**: before the [executor](project-structure.md) emits a
  remediation PR, the analyzer checks that the change would actually land in the
  target scope. A blocking finding degrades the action to `hil` rather than
  opening a PR that would fail policy.
- **Human deploy**: as a standalone CI check on an infrastructure PR, the report
  is posted as a PR comment / GitHub Check so an operator sees blockers before
  `terraform apply`, not after.

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
[rule-catalog-collection.md](rule-catalog-collection.md) for how the underlying
rules are sourced.

## Readiness Report

Findings are assembled into one `DeploymentReadinessReport`
([core/deploy_preflight/report.py](../../src/aiopspilot/core/deploy_preflight/report.py)).
Each finding carries three required parts:

- **evidence** - a CSP-neutral citation of the rule that produced it
  (`policy:<neutral-id>`, `nsg:<neutral-id>/rule:<name>`). A probe that cannot
  cite a source MUST NOT emit a finding; an ungrounded blocker is a defect, the
  same rule the T2 verifier follows.
- **severity** - `blocking` (gates an enforce-mode deploy) or `warning`
  (surfaces but never gates).
- **resolution** - how to clear it, mapped to a concrete lever when possible
  (see the toggle table below).

### Verdict Semantics

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
same promotion discipline the [ActionType contract](llm-strategy.md) applies to
autonomous actions.

## Blocker to Terraform Toggle Mapping

A report is not just a list of problems; each `terraform_toggle` finding names
the infra sub-module and variable override that makes the deployment comply.
This reuses the existing `infra/modules/<seam>/` + `var.<seam>_kind` selection
pattern ([project-structure.md](project-structure.md)), generalized to
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
| Probe seam | [shared/providers/feasibility_probe.py](../../src/aiopspilot/shared/providers/feasibility_probe.py) | `FeasibilityProbe` Protocol + finding / target dataclasses |
| Generic probes | [shared/providers/local/feasibility.py](../../src/aiopspilot/shared/providers/local/feasibility.py) | deterministic, config-driven upstream defaults (no network) |
| Orchestrator | [core/deploy_preflight/analyzer.py](../../src/aiopspilot/core/deploy_preflight/analyzer.py) | fan out over probes, assemble the report (fail-closed) |
| Report | [core/deploy_preflight/report.py](../../src/aiopspilot/core/deploy_preflight/report.py) | the assembled artifact + verdict + `blocks_deploy` |

`core/` sees only the `FeasibilityProbe` Protocol; the probes are injected at the
[composition root](../../src/aiopspilot/composition.py) via the
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
  ([architecture.instructions.md § Rule Catalog](../../.github/instructions/architecture.instructions.md#rule-catalog)).

## Delivery Increments

Shipped now: the probe seam, the generic deterministic probes, the analyzer +
report, composition wiring, and tests. Next increments, staged so each is
separately reviewable:

1. Live Azure adapters under `delivery/azure/preflight/` (Policy Insights,
   Resource Graph, Firewall / NSG, Quota), shadow-mode first.
2. The `infra/modules/` capability-mode toggles in the table above.
3. A GitHub Check that posts the report on an infrastructure PR.
4. A cached **Deployment Environment Profile** (which guardrails apply to a
   scope), refreshed via the Inventory delta stream so a deploy reads the cache
   instead of re-probing.

## References

- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) - control loop, quality gate, safety invariants
- [project-structure.md](project-structure.md) - module boundaries, infra sub-module pattern
- [risk-classification.md](risk-classification.md) - how a blocking finding routes to `hil`
- [rule-catalog-collection.md](rule-catalog-collection.md) - where the underlying guardrail rules come from
