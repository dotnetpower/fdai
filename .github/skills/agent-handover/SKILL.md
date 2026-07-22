---
name: agent-handover
description: |
  Runbook for the FDAI agent-stewardship handover: map the real humans who
  did operational work (or several jobs at once) onto the fixed 15-agent
  pantheon, so every agent has an accountable human for escalation and
  knowledge handover, and FDAI itself has 1+ (recommended 2) maintainers.
  Load this skill when onboarding a customer/team, when filling or reviewing
  `config/agent-stewardship.yaml`, when a `check-stewardship.sh` gate fails,
  or when someone asks "who owns agent X now that FDAI runs it". For the
  design of record see
  `docs/roadmap/interfaces/agent-stewardship-and-handover.md`; for the
  always-on rules see `.github/instructions/agent-stewardship.instructions.md`.
version: 1.0.0
scope: repository
---

# Agent Handover Runbook

The handover maps **who used to do the work** onto the 15 agents that now do it.
It is an accountability + notification overlay: a steward is an escalation and
review contact, not an executor. RBAC (what a person may operate) is a separate
axis - do not conflate them.

## Preflight (answer first)

1. Are you adding/removing/renaming an agent? **Stop** - the pantheon is fixed at
   15. Handover only assigns humans to the existing agents.
2. Are you trying to change who *executes / judges / approves* an action? **Stop** -
   those bindings are fork-locked in the ontology. Handover never repoints them.
3. Do you have real Entra objectIds (user and/or group) for the people involved,
   plus at least one FDAI maintainer (two recommended)?

## The 15 agents and the question that maps each

Ask "who did this, or would be paged for this?" for each agent's domain:

| Agent | Domain question ("who owned...") |
|-------|----------------------------------|
| Odin | cross-team prioritization / final tie-break on conflicting changes |
| Thor | executing approved changes (the human who ran the runbooks) |
| Forseti | deciding whether a change is safe / allowed (change-approval owner) |
| Huginn | event/alert intake and triage |
| Heimdall | monitoring, anomaly/drift watching, on-call observation |
| Vidar | rollback / DR / failover ownership |
| Var | approving high-risk operations (the approver on call) |
| Bragi | the person who explains ops status to stakeholders |
| Saga | audit / compliance / record-keeping owner |
| Mimir | rule / policy / standards ownership |
| Muninn | runbook / knowledge-base / institutional memory owner |
| Norns | continuous-improvement / postmortem-to-rule owner |
| Njord | cost / FinOps owner |
| Freyr | capacity / sizing / performance owner |
| Loki | chaos / resilience testing owner (often none standing -> autonomous) |

One person may map to several agents (1-person-many-roles) and one agent may map
to several people (many-people-1-role). Both are expected. Prefer at least two
distinct `accountable` people on any agent whose loss would hurt (avoid
bus-factor 1).

## Procedure

1. **Interview.** For each of the 15 rows above, record the accountable person(s)
   and any informed stakeholders. Note where nobody owns it (candidate
   `accept_autonomous`).
2. **Resolve identities.** Get the Entra **user** objectId for each person, or the
   **group** objectId for a team. Personal channel bindings (optional) map an OID
   to a `notifications-matrix.yaml` channel-id.
3. **Fill the config.** Edit `config/agent-stewardship.yaml`:
   - `maintainers:` 1+ (2 recommended),
   - each agent's `stewards:` with `kind` / `id` / `responsibility`,
   - `accept_autonomous: { reason: ... }` for any agent with no accountable human.
4. **Validate (the verification step).** Work the checklist below until clean.
5. **Land it as a governance PR.** The console never writes this file directly.
   An Owner may edit the file, or upload a `handover_bootstrap` document. When
   stewardship governance is enabled, the grounded draft opens one idempotent
   draft PR. A signed merge webhook notifies affected stewards + maintainers and
   writes the Saga merge audit.

## Verification checklist (must pass before handover is "done")

- [ ] `bash scripts/governance/check-stewardship.sh` is green (15 agents, maintainer floor,
      no forbidden role fields).
- [ ] `pytest tests/core/stewardship/ -q --no-cov` passes.
- [ ] `python -c "from pathlib import Path; from fdai.core.stewardship import
      load_stewardship_from_yaml, build_coverage_report as r;
      print([f.code for f in r(load_stewardship_from_yaml(Path('config/agent-stewardship.yaml'))).warnings])"`
      shows no **unexpected** warnings. Expected residuals to review:
  - `maintainer_single` -> appoint a second maintainer,
  - `bus_factor_one` -> add a second accountable steward where the loss would hurt,
  - `over_assigned` -> spread load off any one over-loaded person.
- [ ] In a deployment, no id is left at the all-zero placeholder (`FDAI_STEWARDSHIP_REQUIRE_BINDINGS=1` load
      raises otherwise; `check-guids.sh` also blocks it).
- [ ] Every agent is either mapped to an `accountable` steward or explicitly
      `accept_autonomous` with a reason - never silently unowned.
- [ ] Two maintainers configured (1 is allowed but flagged).
- [ ] In a deployment, `GET /stewardship` returns all 15 agents and the latest
   `stewardship_health:current` snapshot is recent.
- [ ] When governance delivery is enabled, reprocessing one synthetic handover
   upload returns the same PR, and replaying one GitHub delivery id writes no
   second merge audit or notification.

## Common gotchas

- **Group vs user.** A `group` steward is expanded best-effort; if Graph is down
  it is treated as one opaque unit on the domain channel. Use a `user` OID when
  you need a specific person paged first.
- **`accept_autonomous` is not "no owner".** It routes escalation to the
  maintainer. Use it only when there is genuinely no standing domain owner
  (Loki is the upstream default example).
- **Do not localize the config.** Reasons and keys are L0 English. The console
  view localizes labels around the values, never the values.
- **Stale OIDs.** When a steward leaves, the scheduled `audit_stale_oids` check
  flags them and they fall through to the next tier / maintainer. Update the
  config via PR; do not leave a dead OID as the only accountable steward.
