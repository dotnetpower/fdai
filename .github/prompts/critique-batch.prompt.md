---
mode: agent
description: One critique -> harden -> verify batch on a safety-core module.
---

# /critique-batch - one focused critique + harden cycle

Do one honest bug-finding batch on a safety-core module. **One batch =
one focused change + one commit.** The loop is documented in
`/memories/repo/coding-ability.md`; this prompt is the executable form.

## Priority modules (safety core, >= 90% coverage floor)

Pick one that has NOT already been hardened this session:

- `services/core-control-plane/src/fdai/core/risk_gate/`
- `services/core-control-plane/src/fdai/core/tiers/t0_deterministic/`
- `services/core-control-plane/src/fdai/core/tiers/t1_lightweight/`
- `services/core-control-plane/src/fdai/core/tiers/t2_reasoning/`
- `services/core-control-plane/src/fdai/core/quality_gate/`
- `services/core-control-plane/src/fdai/core/executor/`
- `services/core-control-plane/src/fdai/core/event_ingest/` (idempotency + dedup)
- `services/core-control-plane/src/fdai/core/trust_router/`
- `services/core-control-plane/src/fdai/agents/forseti.py` (Judge)
- `services/core-control-plane/src/fdai/agents/var.py` (Approver)
- `services/core-control-plane/src/fdai/agents/thor.py` (Responder)

## Steps

1. Read the module and its neighbors.
2. **Critique honestly**: list real bugs, missing safety invariants
   (stop condition / rollback / blast radius / audit), off-by-one, race
   or ordering hazards, fail-open branches. **Do not fabricate.** If no
   real defect is found, say so and pick a different module. Recording
   "false-positive after re-verification" is a legitimate outcome.
3. **Harden**: fix ONE finding. Do not blend unrelated fixes.
4. **Verify**:
   - `bash scripts/verify.sh --fast`
   - Targeted pytest for the touched module, with coverage:
     `pytest services/core-control-plane/tests/<matching_path> -q --no-cov` (or a coverage run if
     coverage is at risk).
   - Safety-core property tests must still pass unchanged.
5. **Docs-first / docs-after**: if behavior, DI seam, config key, or a
   schema changed, update the affected docs (English + `-ko.md`) in the
   same commit.
6. Per-file `git add`, then `fix(<scope>): ...` or `harden(<scope>): ...`.

## Guardrails

- **Fail closed**: ambiguity / verification failure / unexpected error
  MUST abstain or HIL, never auto-change. No empty catch, no bare
  except. Errors carry context.
- **No defensive code for impossible states**: validate at boundaries
  only; if the type system already excludes the state, do not add a
  guard. See the `lock.py::snapshot()` false-positive lesson in
  `/memories/repo/coding-ability.md`.
- **Agent code = pantheon rules**: any file under `services/core-control-plane/src/fdai/agents/**`
  MUST follow the fork-locked role bindings (executor / judge /
  approver / auditor / initiators). See
  `.github/instructions/agent-pantheon.instructions.md`.
- **Async seams**: EventBus / StateStore / SecretProvider /
  WorkloadIdentity / Inventory are `async`. SchemaRegistry /
  ContractValidator / ConfigProvider are sync. Do not flip either.
- **customer-agnostic** at all times. No real sub / tenant / customer /
  endpoint strings.

## When to stop

- One finding hardened, gates green, commit landed -> stop this batch.
  Return control to the caller. The caller can immediately invoke
  another `/critique-batch`.
