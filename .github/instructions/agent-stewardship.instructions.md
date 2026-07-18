---
description: Agent stewardship + handover map rules for the config and core module.
applyTo: "config/agent-stewardship.yaml,src/fdai/core/stewardship/**"
---

# Agent Stewardship - Handover Map Contract

Normative rules for editing `config/agent-stewardship.yaml` and any file under
`src/fdai/core/stewardship/**`. The design of record is
[../../docs/roadmap/interfaces/agent-stewardship-and-handover.md](../../docs/roadmap/interfaces/agent-stewardship-and-handover.md).
Related: [agent-pantheon.instructions.md](agent-pantheon.instructions.md)
(the fork-locked role bindings this overlay must not touch),
[coding-conventions.instructions.md](coding-conventions.instructions.md),
[language.instructions.md](language.instructions.md).

RFC 2119 keywords apply: **MUST** / **MUST NOT** are hard gates; **SHOULD** is a
strong default; **MAY** is optional.

## 1. It is an overlay, not an authorization surface (MUST)

- Stewardship maps humans to agents for **accountability and notification only**.
  It MUST NOT change or restate any pantheon `ActionType` role binding. The five
  fork-locked fields (`initiators`, `judge`, `executor`, `approver`, `auditor`)
  live only in the ontology. The stewardship config MUST NOT contain a top-level
  key named any of those; `scripts/governance/check-stewardship.sh` rejects it.
- A steward is never granted the executor Managed Identity, an approval
  capability, or any RBAC role by virtue of being a steward. RBAC
  ([user-rbac-and-identity.md](../../docs/roadmap/interfaces/user-rbac-and-identity.md))
  is a separate, independently-resolved axis.

## 2. The 15-agent set is fixed (MUST)

- The `agents:` block MUST name **exactly** the 15 pantheon members, spelled
  exactly. Missing or unknown names fail fast at load and in CI.
- `core/stewardship/names.py::AGENT_NAMES` is the module-local mirror of
  `PANTHEON_NAMES`. `core/` MUST NOT import `agents/` (module boundary); keep the
  mirror in sync through `tests/core/stewardship/test_pantheon_parity.py`, never
  by importing the pantheon into `core/`.

## 3. Steward and maintainer shape (MUST)

- Every agent MUST have at least one `accountable` steward **or** an
  `accept_autonomous` block with a non-empty `reason`. An agent with neither is
  rejected.
- A steward subject is `kind: user | group` + a UUID-shaped Entra objectId +
  `responsibility: accountable | informed`. Both `user` and `group` subjects are
  allowed; a `group` is expanded best-effort through the injected
  `GroupMembershipProvider` and never blocks the control loop.
- There MUST be at least **1** maintainer (fail-fast). Exactly 1 is a warning;
  **2** are recommended. The maintainer set is the final escalation for any agent
  with no live steward.

## 4. Customer-agnostic placeholders (MUST)

- Upstream ships every objectId as the all-zero placeholder. A fork MUST replace
  them with real Entra ids; the resolver rejects a leftover placeholder when
  `FDAI_FORK` is set, and `check-guids.sh` blocks any non-placeholder GUID from
  landing upstream. Never commit a real tenant objectId to this repo.

## 5. Core-module discipline (MUST)

- `core/stewardship/**` stays CSP-neutral: no cloud SDK, no HTTP client, no
  `fdai.delivery` import (enforced by `check-core-imports.sh`). Graph access sits
  behind the `IdentityDirectory` / `GroupMembershipProvider` Protocols, which are
  **async** (network I/O seams) and injected at the composition root.
- Keep the SRP split: `names` (data), `model` (dataclasses), `resolver`
  (parse + fail-fast), `coverage` (findings), `escalation` (routing), `directory`
  (seams). A new concern gets its own module, not a bag added to an existing one.

## 6. Change process (MUST)

- **Docs-first / docs-after.** Any change to the config schema, a validation rule,
  a finding code, or a public function MUST update
  `agent-stewardship-and-handover.md` **and** its `-ko.md` in the same change
  (the SHA gate blocks drift).
- Any new fail-fast rule MUST come with a resolver test; any new finding MUST come
  with a coverage test. Run `scripts/governance/check-stewardship.sh` and
  `pytest tests/core/stewardship/` before proposing the change complete.
- Editing the shipped `config/agent-stewardship.yaml` in production is a
  governance draft-PR flow (console is read-only); it notifies the affected
  stewards + maintainer and writes a Saga audit entry.
