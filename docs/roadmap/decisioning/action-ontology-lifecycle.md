---
title: Action Ontology Lifecycle
---

# Action Ontology Lifecycle

This companion defines the design boundaries, lifecycle rules, and live consumer status for the
ActionType ontology. The canonical schema and catalog remain in
[Action Ontology](action-ontology.md).

## Design boundaries and lifecycle

Explicit answers to recurring questions about the ontology's shape, so a
reviewer does not mistake an intentional boundary for a gap.

- **Three orthogonal classification axes are not redundant** (#12).
  `category` (what kind of change), `trigger_kind` (who initiates), and
  `side_effect_class` (what the console tool does) answer different
  questions and are recorded together on the audit entry (§4.3). A change
  to one never implies a change to another.
- **Two autonomy sources compose by strictest-wins, never by conflict**
  (#15). The risk-classification table (Axis A) and `ceiling_by_tier`
  (Axis C) both bound autonomy; the RiskGate takes the `min` over all six
  axes plus the table, so neither can raise the result above the other.
  When a hand-tuned `ceiling_by_tier` seems ignored, the table matched a
  stricter rule - the audit `resolved_ceiling.winning_axis` names which
  one won (§9), so the interaction is always inspectable, not silent.
- **`argument_schema` versioning** (#20). A backward-incompatible change
  to an `argument_schema` (removing a field, tightening a type) MUST bump
  the ActionType `version` (semver major). Audit entries record the
  arguments as received, so a replay reads them against the version that
  was in effect at dispatch time; the loader never reinterprets a past
  argument blob under a newer schema.
- **ActionType retirement** (#21). Retiring an ActionType is a governance
  PR that (a) removes or shadow-only-pins every rule whose `remediates:`
  points at it (the `remediates:` cross-check would otherwise fail the
  load), then (b) removes the ActionType YAML. The loader's dangling
  `remediates:` check guarantees an ActionType cannot be removed while a
  rule still references it, so a retirement cannot leave a dangling ref.
- **Self-modifying governance is bounded** (#24). `governance.*`
  ActionTypes (promote, retire, override-ceiling) change the safety
  envelope itself, so they carry the strictest defaults: `pr_native`
  execution (a reviewed diff), `default_mode: shadow`, and a distinct
  approver (no self-approval - the actor who authors the promotion PR is
  never its approver). `governance.override-ceiling` is downgrade-only
  and time-boxed. The envelope can be *narrowed* through this path but
  never *widened* without a reviewed, quorum-approved PR.
- **Blast traversal depth is a tunable, safe default** (#28). A
  `graph_derived` blast radius walks `contains` + `depends_on` to
  `traversal_depth` (default 2, max 5). A depth-2 walk under-counts a
  transitive chain deeper than 2; the `RequiresInventoryFresh` interface
  plus the `graph_fresh_within_seconds` precondition keep the walk from
  acting on stale graph data, and an instance exceeding
  `max_affected_resources` escalates to HIL. Forks that operate deep
  dependency graphs raise `traversal_depth` per ActionType.

### Consumer implementation status (declared vs. live)

The ontology deliberately declares more than the runtime consumes today.
This is an explicit boundary, not a hidden gap: an ActionType may exist
as catalog-as-code before its dispatcher lands, and it is **inert by
construction** until then. The safety properties below hold regardless of
which consumer is live, so a declared-but-not-yet-dispatched ActionType
cannot act.

- **Inert-by-default is enforced, not assumed** (#5, #8, #9). Every
  shipped `ops.*` and `governance.*` ActionType ships
  `default_mode: shadow` (verified by
  `test_every_shipped_action_type_defaults_to_shadow`). A declared
  ActionType with no live dispatcher judges-and-logs only; it never
  mutates. Promotion to enforce is a separate, gated governance PR.
- **`rule_violation` (remediation) is the live path.** The
  T0Engine -> ActionBuilder -> RiskGate -> Executor loop (§4.1)
  dispatches remediation ActionTypes today. This is the primary
  autonomy surface and is fully wired.
- **`operator_request` -> typed proposal dispatch is live** (#6, #7).
  The optional `/chat/action` route and Bragi proposal sink translate a registered
  operator command into an `ActionProposal`, enforce server-derived RBAC, and publish
  it to the canonical ingress topic. They never call an executor directly. The
  catalog loader validates `argument_schema`; each live command surface remains
  responsible for accepting only its bounded server-owned argument shape.
- **Three `governance.*` dispatchers are P2 backlog** (#8). Only
  `governance.override-ceiling` has a live dispatcher
  (`core/risk_gate/override_writer.py`); `promote-action-type`,
  `retire-rule`, and the runtime `grant-exemption` writer land with the
  P2 PR-native writer. Their YAML entries are inert catalog data until
  then (shadow-default, no dispatcher = no side effect).
- **`live_probe_ref` is live for selected ops actions** (#9).
  `ops.restart-service` and `ops.scale-in` bind the shipped
  `vm_traffic_last_5m` probe. Actions without a probe continue to use the
  static blast bound; a missing referenced probe fails catalog load.
- **Agents read the ontology; they do not free-form reason over it**
  (#10, #11). The autonomy decision is procedural: the RiskGate reads
  ActionType fields (`ceiling_by_tier`, `blast_radius`, `irreversible`,
  `operation`, `interfaces`) deterministically. ObjectType / LinkType
  declarations are validated and drive codegen and the inventory graph
  used for `graph_derived` blast; they are not a free-form knowledge
  graph the pantheon reasons over. This is by design - determinism-first
  keeps the safety core inspectable. A future graph-reasoning consumer
  is additive and does not change any ceiling.
