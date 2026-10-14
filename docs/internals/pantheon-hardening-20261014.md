# Pantheon five-round hardening review

This record tracks the 27 findings from the 2026-10-14 review against the fixed 15-agent
Pantheon. Source fixes, configured bindings, and operational acceptance are separate outcomes.
The starting source revision is `f393f28ced`. The initial focused review passed 772 tests.

## Scope and invariants

The five rounds review cumulative changes and repair demonstrated defects. Agent names,
`PANTHEON_SPECS`, topic ownership, judgment, approval, execution, audit, recovery, and shadow
promotion authority remain unchanged. Bragi remains a read-only conversational translator.
No push, deployment, live model call, provider mutation, or live identity is authorized here.
Synthetic tests never satisfy operational readiness or production promotion.

## Finding inventory

| Review ID | Finding | Current disposition and observable exit |
|-----------|---------|-----------------------------------------|
| 1 | Unsupported T2 conclusions | Hardened boundary in round 2: unbound/rejected/invalid verification cannot display synthesis; actual V-CLAIM/independent-review production binding remains open. |
| 2 | Lost failed discussion participants | Fixed in round 1: preserve all selected participants and reasons; block synthesis after partial evidence. |
| 3 | Peer critique does not consume the peer claim | Open source limitation: attribute structured comparisons to the exact peer evidence without inventing semantic critique. |
| 4 | Template operational answers | Open migration debt: use verified answer composition; keep fact views and role descriptions distinct from operational conclusions. |
| 5 | Remote target and locale are lost | Open source defect: bind an explicit canonical target and validated locale end to end. |
| 6 | Operator group discussion is not wired | Open integration work: expose an authenticated read-only boundary without transferring typed authority. |
| 7 | Concrete T2 synthesis is unbound | Open integration work: bind only a verified, priced, metered implementation. |
| 8 | Narrow structured conflict vocabulary | Bounded design, not proof of complete reasoning: add only typed, evidenced comparisons; never infer conflict from lexical prose. |
| 9 | Process-local discussion budget | Open integration work: retain atomic limits across restarts and replicas using the existing budget seam. |
| 10 | Freyr/Loki recurring bindings absent | Open integration work: bind authoritative read-only sampling and reviewed schedules; do not synthesize samples or authorize Chaos. |
| 11 | Mimir/Bragi maintenance bindings absent | Open integration work: bind reviewed source/regression/promotion/activation readers without granting activation authority. |
| 12 | Durable what-if and multi-target attempt model | Open design/implementation work: prove restart-safe retained inputs and per-target rollback plus aggregate audit. |
| 13 | Ordered poison halt persistence unbound | Open deployment decision: preserve ordered halts through restart and retain an authorized clear receipt. |
| 14 | Saga replica and issue-operation identity residuals | Recorded Low-severity residuals: reproduce before repair; prove one audit/publication and reject cross-fingerprint operation reuse. |
| 15 | Development authority source absent | Open authority binding: use the current exact deployment source; never manufacture or relax authorization. |
| 16 | Workflow/KPI/effect/promotion evidence absent | Operational blocker: retain complete pinned live-shadow cohorts, independent effects, recovery and zero policy escapes. |
| 17 | Generic v1 placeholder ownership map | Intended upstream example, not readiness: a deployment supplies v2 live primary and distinct backup/escalation identities. |
| 18 | Free-prose handover interpreter absent | Open integration work: bind a grounded interpreter; structured input and explicit hold remain safe defaults. |
| 19 | Readiness report is permanently observation-only | Intentional authority boundary: add independent evidence evaluation without allowing a report to self-certify deployment. |
| 20 | GitHub App/merge/restart evidence absent | Operational blocker: retain real refresh, signature, idempotent PR, merge and restart observations. |
| 21 | Executor/replacement identity evidence absent | Operational blocker: retain current target-bound authorization and independent identity/role readback. |
| 22 | Membership recovery drills absent | Operational blocker: run explicitly authorized nonproduction inverse and rollback drills. |
| 23 | Notification/non-response evidence absent | Operational blocker: retain actual channel delivery and recipient progression without treating silence as approval. |
| 24 | Document ACL/deletion/performance evidence absent | Operational blocker: retain source ACL, withdrawal, deletion, legal hold and complete performance cohorts. |
| 25 | Exact-plan deployment acceptance absent | Operational blocker: select release/target and obtain exact-plan human approval outside this local task. |
| 26 | Task-level handover competence absent | Operational blocker: retain coverage, correctness, independent review and task acceptance cohorts. |
| 27 | Real speech/assistive evidence absent | Needs human: retain actual EN/KO speech and screen-reader results; browser simulations are insufficient. |

## Round evidence

| Round | Critique | Repair | Focused evidence | Residual |
|-------|----------|--------|------------------|----------|
| 1 | One failed peer disappeared while a three-participant discussion reported completion. | Preserve selected/attempted participant accounting and return partial or abstain; no synthesis of incomplete branches. | `pytest -q --no-cov test_prompt_deliberation.py test_framework_layout.py`: 60 passed; Ruff and focused mypy passed. | Synthesis grounding, remote dispatch, persistent limits, integrations, and operational acceptance remain open. |
| 2 | Generated prose passed only output-size and sensitivity checks; a fabricated 999-resource claim was accepted. | Require an independent verifier and exact request/conclusion/evidence receipt; hold on absence, rejection, substitution, self-verification or provider failure. | Focused deliberation/layout/bootstrap checks: 82 passed; Ruff and six-file mypy passed. | The verifier contract is tested, not a live independent entailment or production readiness claim. |

## Completion boundary

### Round 2 design and critique

An independent, composition-owned synthesis verifier reads the same bounded request and
generated outcome. Its immutable receipt binds the canonical request digest, exact conclusion
digest, and complete cited evidence set. The generator cannot act as its own verifier. Missing,
timed-out, malformed, mismatched, or rejected verification retains T1 evidence and never displays
an unverified T2 conclusion. Verification is presentation-only and grants no action authority.
The verifier seam is not itself operational validation: a deployment still needs a real
V-CLAIM/independent-review binding and governed receipts. Synthetic acceptance tests establish
the fail-closed transport boundary only.

This record does not label the Pantheon or ownership handover operationally ready. Open items
remain resumable with the exact exits above. A completed local round means only its stated source
repair and focused verification succeeded.
