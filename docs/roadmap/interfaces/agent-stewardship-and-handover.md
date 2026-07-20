---
title: Agent Stewardship and Handover
---
# Agent Stewardship and Handover

How the humans who used to do operational work are mapped onto FDAI's 15-agent
pantheon, so that when FDAI takes over a task there is a named, accountable human
behind each agent for escalation, review, and knowledge handover.

This is a **separate axis** from
[user-rbac-and-identity.md](user-rbac-and-identity.md). RBAC answers "who may
operate FDAI" (Reader / Contributor / Approver / Owner). Stewardship answers "who
owned this work before FDAI, and who is now accountable for this agent's domain".
A person is typically in both models (an Approver who is also Var's steward), but
the two are resolved and validated independently.

> Customer-agnostic: every objectId, group id, and name below is a **placeholder**
> (all-zero UUID). Deployment configuration supplies the real Entra values
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **Implementation status.** Loader/validation, coverage, escalation, deterministic change
> recipient/audit-payload primitives, the read-only console projection, handover document
> ingestion, and Graph person resolution are shipped. Automatic production stewardship-map
> binding, Terraform injection of `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1`, GitHub App draft-PR
> creation, and post-merge notification/audit hooks remain composition/deployment work.

## 1. Design principles

1. **Overlay, never a repointing.** Stewardship maps humans to agents for
   accountability and notification only. It MUST NOT change any pantheon
   `ActionType` role binding. The five fork-locked fields (`initiators`, `judge`,
   `executor`, `approver`, `auditor`) stay exactly as
   [agent-pantheon.md](../agents/agent-pantheon.md) declares them. A steward is
   *not* granted the executor identity by being a steward.
2. **Multiple humans per agent.** A role can be held by several people. Every
   agent maps to a **list** of stewards (personal Entra OIDs and/or Entra group
   objectIds), not a single owner.
3. **A maintainer floor.** FDAI itself needs a named owner. There MUST be at least
   **1** maintainer (fail-fast) and **2** are recommended (warn). The maintainer is
   the final escalation target for any agent with no live steward.
4. **Fail toward a human.** An unmapped agent, a stale steward OID, or a missing
   maintainer degrades to "escalate to the maintainer", never to "silently
   unowned".
5. **Console stays read-only.** The stewardship settings surface renders state;
   edits are authored as draft PRs by the GitHub App, exactly like every other
   governance change ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
6. **Every change must be notified and audited.** Core deterministically computes recipients and
  the audit payload. Live PR/merge integration must bind those primitives to notification and
  audit adapters.

## 2. Concepts and vocabulary

Reuse these terms verbatim in code, config, and docs.

| Term | Meaning |
|------|---------|
| **agent-steward** | A human (or team) accountable for an agent's domain. The person who did this work before FDAI, now supervising the agent and receiving its escalations. |
| **handover-map** | The full mapping of all 15 pantheon agents to their stewards. The artifact produced by an onboarding handover. |
| **maintainer** | A human accountable for the FDAI platform itself. Min 1 (hard), rec 2 (warn). Final escalation for unmapped agents. |
| **responsibility (RACI-lite)** | Each steward entry is tagged `accountable` or `informed`. Every agent MUST have at least one `accountable` steward unless it is explicitly `accept_autonomous`. |
| **accept_autonomous** | An explicit acknowledgement that an agent runs fully autonomously with no domain steward. Escalation falls back to the maintainer. Requires a `reason`. |
| **escalation-chain** | The ordered notification path for an agent: `accountable` stewards -> `informed` stewards -> maintainer, with a per-hop timeout. |
| **bus-factor** | The number of distinct `accountable` humans who know an agent's domain. A bus-factor of 1 is a tracked risk (warn). |

### RACI-lite, not full RACI

Full RACI (Responsible / Accountable / Consulted / Informed) is more than a
handover needs and invites bikeshedding. This model keeps two tags:

- **accountable** - on the escalation hot path; is paged first; must be a human
  who can act or delegate.
- **informed** - notified for awareness (change notifications, post-incident), not
  on the first escalation hop.

"Responsible" collapses into the agent itself (FDAI does the work) and "Consulted"
collapses into `informed`.

## 3. Relationship to RBAC and notifications

```text
                 who may operate FDAI            who owns the work
                 (user-rbac-and-identity)        (this doc)
 human  ------>  Role: Reader/Contributor/    +   Steward-of: {agents...}
                 Approver/Owner/BreakGlass         responsibility: accountable|informed
                        |                                   |
                        v                                   v
                 capability gate                    escalation + change-notify
                 (core/rbac)                         (core/stewardship -> core/notifications)
```

- **RBAC gates the action** (can this person approve the HIL request at all?).
- **Stewardship routes the notification** (which person for *this* agent gets
  paged first?).
- A steward who is paged to approve a HIL request still passes through the RBAC
  `Approver` capability check and the no-self-approval check. Being a steward
  grants no approval capability by itself.

## 4. Data model

### 4.1 Config artifact

`config/agent-stewardship.yaml` (fork supplies real values; upstream ships
placeholders):

```yaml
stewardship:
  version: 1

  # FDAI platform owners. Min 1 (fail-fast), rec 2 (warn on 1).
  maintainers:
    - oid: "00000000-0000-0000-0000-000000000000"   # Entra user objectId
    - oid: "00000000-0000-0000-0000-000000000000"

  # Optional per-person notification channel binding (person OID -> channel-id
  # known to notifications-matrix.yaml). Missing entries fall back to the
  # agent's category route in the matrix.
  channels:
    "00000000-0000-0000-0000-000000000000": teams-hil-prd

  # Escalation timing (seconds per hop before advancing to the next tier).
  escalation:
    hop_timeout_seconds: 900        # accountable -> informed -> maintainer

  # All 15 pantheon agents MUST appear. A subject is a personal OID or an
  # Entra group objectId; `kind` disambiguates. `responsibility` is
  # accountable|informed. An agent with no accountable steward MUST set
  # accept_autonomous with a reason.
  agents:
    Odin:
      stewards:
        - { kind: user,  id: "00000000-0000-0000-0000-000000000000", responsibility: accountable }
        - { kind: group, id: "00000000-0000-0000-0000-000000000000", responsibility: informed }
    Thor:
      stewards:
        - { kind: user,  id: "00000000-0000-0000-0000-000000000000", responsibility: accountable }
    Loki:
      accept_autonomous:
        reason: "Chaos proposals are always HIL; no standing domain owner."
      stewards: []
    # ... all 15: Odin, Thor, Forseti, Huginn, Heimdall, Vidar, Var, Bragi,
    #     Saga, Mimir, Muninn, Norns, Njord, Freyr, Loki
```

### 4.2 Env-var overrides

A fork MAY override single slots without editing YAML (mirrors the rbac-groups
pattern):

| Env var | Effect |
|---------|--------|
| `FDAI_MAINTAINERS` | Comma-separated OIDs; replaces the `maintainers` list. |
| `FDAI_STEWARD_<AGENT>` | Comma-separated `user:<oid>` / `group:<oid>` tokens; replaces that agent's `stewards`. `<AGENT>` is upper-case (`FDAI_STEWARD_THOR`). |

### 4.3 Agent-name integrity

The 15 keys under `agents:` MUST be exactly the pantheon names. `core/stewardship`
carries its own canonical `AGENT_NAMES` tuple and a parity test
(`tests/core/stewardship/test_pantheon_parity.py`) pins it to
`fdai.agents._framework.pantheon.PANTHEON_NAMES`, so the config schema and the
pantheon can never drift. `core/` does not import `agents/` (module-boundary rule);
the parity test bridges them at test time instead.

## 5. Maintainer rules

- **Floor (fail-fast):** 0 maintainers is a startup `ValueError`. FDAI does not
  boot the stewardship layer unowned.
- **Recommendation (warn):** exactly 1 maintainer logs a `stewardship_maintainer_single`
  warning and surfaces a console banner. 2+ is clean.
- **Succession:** when a maintainer OID goes stale (removed from Entra, see 7.3)
  and the live count drops to 1, the warning escalates to a **hard banner** asking
  an Owner to appoint a replacement. It does not block the control loop; it blocks
  a clean validation state.
- **Final escalation:** any agent that resolves to zero live stewards routes its
  escalation to the maintainer set.

## 6. Runtime effect: notification and escalation (decision B)

Stewardship is wired into [channels-and-notifications](channels-and-notifications.md)
so an agent's domain steward is notified first for that agent's events.

### 6.1 Escalation chain

For an agent event that needs a human (HIL request, degraded state, workflow-change
request), `core/stewardship` builds an ordered recipient list:

1. the agent's `accountable` stewards,
2. then its `informed` stewards,
3. then the maintainer set.

Each hop has a `hop_timeout_seconds` budget. If no acknowledgement arrives, the
next tier is notified. This reuses the notifications matrix `on_all_fail:
hil_escalate` semantics (a message is never dropped) and extends it with the
person-tier ordering.

### 6.2 Person -> channel bridge

The notifications matrix routes by **channel-id**, but a steward is a **person**.
The bridge resolves, in order:

1. an explicit `channels[<oid>]` binding in `agent-stewardship.yaml`,
2. otherwise the agent's category route in `notifications-matrix.yaml`
   (the person is reached on the domain channel).

A group-objectId steward always resolves through the matrix category route (a
group has no single personal channel).

### 6.3 Group stewards

A `kind: group` steward means "whoever is in this Entra group is a steward". The
resolver expands it to the group's members through an injected
`GroupMembershipProvider` (Graph-backed in a fork, static in tests). Expansion is
best-effort: if the provider is unavailable, the group is treated as one opaque
`accountable` unit routed on the domain channel, and a warning is logged. The
control loop never blocks on Graph.

## 7. Validation gates (the verification surface)

Handover correctness is safety-relevant, so validation is layered.

### 7.1 Loader fail-fast (`load_stewardship_from_mapping`)

Hard errors (raise `StewardshipValidationError`, block a clean boot of the layer):

- fewer than 1 maintainer,
- an `agents:` block missing any of the 15 pantheon names, or naming an unknown
  agent,
- an agent with neither an `accountable` steward nor `accept_autonomous`,
- an `accept_autonomous` without a `reason`,
- a malformed subject (`kind` not in {user, group}, id not a UUID shape),
- when `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1`, any steward or maintainer id left at the
  all-zero placeholder. Every deployed environment that binds a stewardship map must set this
  flag explicitly; fork status is irrelevant.

### 7.2 Non-blocking findings (warn, surfaced in the coverage report)

- exactly 1 maintainer (`maintainer_single`),
- an agent whose bus-factor (distinct accountable humans) is 1 (`bus_factor_one`),
- a person who is `accountable` for more than `N` agents (`over_assigned`,
  default N=5, configurable),
- an agent relying on `accept_autonomous` (`autonomous_no_steward`, informational).

### 7.3 Stale-OID detection

An injected `IdentityDirectory` (Graph-backed in a fork, static in tests) is asked
to confirm each maintainer/steward OID still resolves to an active account. A
missing OID produces a `stale_oid` finding and the person is dropped from live
escalation (falling through to the next tier / maintainer). This runs off the hot
path (scheduled), never inline in the control loop.

### 7.4 CI gate (`scripts/governance/check-stewardship.sh`)

Runs in `scripts/verify.sh` and CI:

- YAML parses and all 15 agent names are present and spelled exactly (compared to
  `PANTHEON_NAMES` via a tiny Python shim),
- the file does not attempt to declare any ActionType role field (grep guard: the
  stewardship file MUST NOT contain `executor:`/`judge:`/`approver:`/`initiators:`/
  `auditor:` keys - those live only in the fork-locked ontology),
- placeholder policy: tracked upstream config requires all-zero values; deployed environments
  require non-placeholder bindings through `FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1`.

## 8. Workflow-change notification and audit (integration target)

A "defined workflow" is any governance artifact that encodes how work flows:
`rule-catalog/workflows/*.yaml`, `config/agent-stewardship.yaml`,
`config/notifications-matrix.yaml`. When a person wants to change one:

The lifecycle below is the target contract. Recipient and audit-payload primitives in
`core/stewardship/notify.py` are implemented; the GitHub App and merge hook are not wired yet.

1. **Draft PR.** The change is authored as a draft PR by the GitHub App (console
   never mutates directly). Standard CODEOWNERS + no-self-approval + quorum apply.
2. **Notify stakeholders.** `core/stewardship` computes the affected agents (for a
   workflow file, the agents it references; for the stewardship file, the agents
   whose stewards changed) and notifies their `accountable` + `informed` stewards
   plus the maintainer: "person X requests a change to workflow Y".
3. **Audit.** A Saga append-only `AuditEntry` records actor OID, artifact, before
   -> after summary, correlation id, timestamp, and the approval decision. The
   audit entry is L0 English and never suppressed.

This closes the loop: the same people who are accountable for an agent are the
people told when its governing workflow is about to change, and the change is
permanently recorded.

## 9. Console settings surface

The read-only Handover view at `console/src/routes/handover.tsx` contains two sections:

- **Handover map** - 15 agent cards, each showing its stewards (resolved display
  names via Graph), responsibility tags, bus-factor, and a validation badge
  (clean / warn / fail).
- **Maintainers** - the maintainer list with the min-1/rec-2 status banner.

The console currently shows "Propose a change" guidance and the config path; it provides no
mutation button or GitHub App call. An Owner edits `config/agent-stewardship.yaml` and opens a
draft PR. The loader rejects fewer than one maintainer; the console shows a recommendation banner
below two.

## 10. Security and safety

- Stewardship never holds or grants the executor Managed Identity.
- Changing the map is a governance PR (author != approver, audited), not a console
  button.
- Steward OIDs are the only identity used for routing and audit; UPN/email are
  informational and never authoritative (same rule as `Principal`).
- No customer-identifying value enters this repo; a fork supplies real OIDs, group
  ids, and channel ids via config or env.

## 11. Handover bootstrap (document ingestion)

Instead of hand-filling the map, an operator MAY upload existing operational
documents (RACI matrices, on-call schedules, org charts, runbooks, handover
memos) and have FDAI parse them into a **draft** steward map for review
([issue #23](https://github.com/dotnetpower/fdai/issues/23)). This is a larger,
separable capability layered on top of the deterministic core above; it never
applies anything and never blocks the core.

Implemented under `src/fdai/core/stewardship/handover_bootstrap/` as a
deterministic-first, grounded, abstaining pipeline:

1. **Deterministic extraction** (`extractor.py` + `agent_domains.py`). Each
   document line is scanned against a per-agent domain-keyword catalog (the
   "who owned X" questions from the handover skill, one entry per pantheon
   agent). A line that hits a domain keyword, a person/team, and a
   responsibility marker yields a grounded `ExtractedMapping` **without a
   model**. This is the deterministic-first stage.
2. **Model interpretation** (`interpreter.py`). What structure cannot resolve
   MAY be handed to a T2 `HandoverInterpreter` seam. Upstream ships
   `AbstainingInterpreter` (proposes nothing) so a deployment without an LLM
   never guesses; a fork binds a mixed-model, grounded implementation
   (symmetric to the `core/rca` reasoner seam). A model proposal that is not
   grounded is discarded by the orchestrator.
3. **Identity resolution** (`people.py`). Each mentioned name/team is resolved
  to an Entra object id through the async `PersonDirectory` seam. Production
  binds `GraphPersonDirectory`, which accepts one exact active user or group
  display-name match and abstains on zero or ambiguous matches. An unresolved
  name is **flagged, never guessed** into an id; the local default
  (`NullPersonDirectory`) resolves nothing.
4. **Confidence floor + draft assembly** (`bootstrap.py`). Grounded mappings at
   or above the floor become the draft; below-floor mappings are set aside for
   a human, unresolved people and agents with no confident owner are surfaced,
   and a run with nothing above the floor abstains. The output is a
   `StewardMapDraft`.

The document-ingestion gateway accepts `handover_bootstrap` as an explicit
`DocumentPurpose`. After quarantine, protection checks, and extraction complete,
`DocumentIngestionWorker` dispatches the safe `DocumentEnvelope` to the injected
`DocumentReadyConsumer` for that purpose. Both local and production compositions
bind `HandoverBootstrapConsumer` and expose the result through authenticated
`GET /ingestion/uploads/{upload_id}/handover-draft`. The console polls the processing
state and renders the draft JSON summary and YAML for review. It doesn't apply the map
or create a privileged mutation path. Local development stores drafts in memory;
production stores them through `PostgresStateStore`, so a worker or gateway restart
doesn't lose the review artifact.

Production Graph calls use the gateway's managed identity and the
`https://graph.microsoft.com/.default` scope. Assign only the Microsoft Graph
application permissions needed for exact lookup (`User.Read.All` and
`Group.Read.All`), and review them regularly. The adapter doesn't log names, object
ids, tokens, or provider response bodies. `FDAI_GRAPH_BASE_URL` is an optional
test/sovereign-cloud override; the public Graph v1.0 endpoint is the default.

Every emitted mapping cites its source span (`SourceSpan`), so nothing is
ungrounded. `draft_yaml.py` renders the draft as `stewardship:`-shaped YAML that
**round-trips through `load_stewardship_from_mapping`** (the same resolver and
fail-fast gates), with inline citation comments and placeholder ids for
unresolved people. The delivery layer surfaces that YAML as a governance draft
PR a human reviews and merges - the console stays read-only, and no map is ever
applied autonomously.

The remaining fork binding is `HandoverInterpreter` for grounded T2 interpretation
of structure the deterministic extractor cannot resolve. Upstream production keeps
the abstaining implementation unless a mixed-model binding is explicitly supplied;
deterministic extraction and Graph resolution still run. All seams are async and
injected; `core/` holds neither a cloud SDK nor an HTTP client.

## 12. Out of scope (tracked separately)

- Non-Azure identity providers (TBD per
  [Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).
