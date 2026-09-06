# Operational diagnostic conversations implementation ledger

This ledger owns delivery status for the bilingual operational diagnostic conversation contract.
It separates coordinating-session reports from retained final-snapshot and interactive evidence.

> **Evidence boundary:** The source baseline is `c5380e434`, not a commit containing these changes.
> Component work is uncommitted and isolated. The reported results below were supplied by the
> coordinating session, not rerun by this documentation-only change. Durable exact-command and
> runtime receipts are not reconstructed here; these reports do not certify the deployed runtime.
> No tests, lint, build, live request, or commit ran as part of this documentation task.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Four-family acceptance contract | not-applicable | `current change`; bilingual [design owner](../../roadmap/interfaces/operational-diagnostic-conversations.md) | Design-only acceptance, paraphrases, boundaries, and gap coverage; not executable completion. |
| Fresh inventory document component | implemented | Reported 37 targeted tests passed; `document_export.py`, `semantic_turn_runtime.py`, and [Operator tests](../../../services/operator-service/tests/); [Core conversation tests](../../../services/core-control-plane/tests/conversation/) | Isolated component result only. Interactive acceptance remains open in the separate row below. |
| Native metric concepts | implemented | Reported 24 native concepts; `metric-semantics.yaml`, `metrics_api.py`, `metrics_api_queries.py`; [Azure delivery source](../../../services/core-control-plane/src/fdai/delivery/azure/) | A test slice had 103 passes before two constructor-fixture fixes; five focused guard tests subsequently passed. Counts overlap and are not additive. No full post-fix slice pass is claimed. |
| Scoped configuration comparison | in-progress | [Ontology platform source](../../../services/core-control-plane/src/fdai/core/ontology_platform/); coordinating-session revision report | Prevent global history references from leaking through scoped values, receipts, or aggregate evidence. Current implementation evidence is incomplete. |
| Compound gateway metric/configuration wiring | in-progress | [Core conversation source](../../../services/core-control-plane/src/fdai/core/conversation/); coordinating-session progress report | AppGW/backend and APIM/GPT questions still need connected, scoped, typed evidence. |
| Standard interactive acceptance | in-progress | Reported document request: action draft, no artifact, about 39.9 seconds. Reported gateway question: held with `semantic_frame_unavailable`. | Neither observation is an answer-quality pass; no successful interactive evidence is claimed for any of the four families. |
| Formal critique and hardening | not-started | No completed round receipt; round requirements below | 0 of at least 10 rounds completed. Design critique, unrelated campaigns, and test counts do not substitute for rounds. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-06 | in-progress | Adopted the four-family contract and this ledger without reconstructing earlier provenance or commits. Recorded reported component progress separately from unsuccessful interactive observations. | `current change`; `docs/roadmap/interfaces/operational-diagnostic-conversations.md` and `operational-diagnostic-conversations-ko.md`; source locations and bounded reported outcomes in the scope table. This documentation task ran no executable checks. | Close scope and compound-wiring gaps, retain exact final-snapshot evidence, obtain accepted interactive answers/artifact, and complete at least 10 formal rounds. |

### Remaining work

- [ ] Retain exact focused command, outcome, and source snapshot for the 37-test document component
  result; verify current-turn/principal binding, complete source/export handling, and zero-row cases.
- [ ] Retain a final-snapshot native-metric result after both constructor-fixture fixes. Identify
  which checks overlap with the reported 103-pass slice and five guard passes; never sum them.
- [ ] Finish configuration scope revision with evidence that unrelated object identifiers, property
  paths, history references, and aggregate provenance never appear in authorized scoped output.
- [ ] Finish compound wiring so F3 and F4 return independently attributed metric windows and scoped
  configuration changes, or precise per-goal limitations without a fabricated complete diagnosis.
- [ ] Retain standard interactive receipts for each family's canonical request and three generic
  paraphrases in English and Korean. Record exact scope/time, terminal state, goal coverage,
  evidence completeness, latency, and F1 artifact retrieval. Resolve the observed document action
  draft and gateway semantic-frame hold; do not infer a pass from component checks.
- [ ] Retain safe negative outcomes for ambiguity, missing/denied evidence, pagination limits,
  stale history, unavailable metric dimensions, zero versus no samples, and no-mutation boundaries.
- [ ] Complete the ten rounds below and append actual outcomes. Resolve every accepted finding or
  keep the affected acceptance condition open with a precise blocker and next evidence requirement.
- [ ] Before claiming all gaps closed, confirm every family meets its contract, all accepted
  findings are resolved, and final-snapshot and standard interactive evidence are retained.

## Formal critique and hardening rounds

All rounds below are **not started**. They are resumable acceptance obligations, not fabricated
review history. Each executed round records its reviewed snapshot and scope, critique hypothesis,
finding and severity, accepted fix or reason for rejection, exact focused validation command and
outcome, evidence reference, and remaining blocker. A no-finding round still needs review evidence.

| Round | Critique focus | Observable exit condition |
|-------|----------------|---------------------------|
| R01 | Principal and scope isolation | Read, traversal, aggregate, and export evidence exclude unrelated objects and global history references. |
| R02 | Whole-request semantic interpretation | Each family's canonical request and three paraphrases preserve typed goals in both languages; ambiguity holds instead of keyword routing. |
| R03 | Time and historical coverage | Absolute boundaries, time zones, equal-duration windows, effective/recorded times, stale samples, and absent baselines stay explicit. |
| R04 | Capacity and units | Capacity units, TPM, quota, token consumption, counts, rates, and time units cannot be silently substituted or converted. |
| R05 | AppGW/backend native semantics | Total/connect/first-byte/last-byte timings retain provider meaning; aggregation differences never become an invented gateway-only duration. |
| R06 | APIM/GPT attribution | `GatewayResponseCode` and `BackendResponseCode` remain separate for `429`/`500`/`503`; GPT metrics retain verified deployment scope and rate denominators. |
| R07 | Enumeration and completeness | Multi-page, duplicate, row/column/byte-limit, truncated, and complete-empty cases preserve source/export distinctions and bounded behavior. |
| R08 | Missing and failed evidence | Zero, no samples, unsupported, denied, stale, absent history, and provider failure remain distinguishable; no fabricated zero or "no changes". |
| R09 | Artifact and replay binding | A fresh inventory artifact binds to this turn and principal, survives authorized retrieval, and never reuses an unrelated result or widens scope. |
| R10 | Compound behavior and authority | Standard interactive answers cover metrics plus changes without causal overclaim or mutation; failure/cancellation deadlines remain bounded. |

R01-R10 do not authorize live mutations. Authorized live reads and model questions remain bounded;
TPM reduction and chaos injection remain outside scope. Stop the attempt on unexpected model
fallback, HTTP `429`/`503`, provider timeout, or deadline expiry.

## Documentation handoff

Only this ledger and the bilingual design owner belong to this documentation change. Existing
implementation edits remain untouched. Refresh only the owned translation:

```bash
python3 scripts/quality/localization/refresh-translation-sha.py \
  docs/roadmap/interfaces/operational-diagnostic-conversations-ko.md
```

Suggested narrow translation review command for the coordinating session; **not run here**:

```bash
python3 scripts/quality/localization/check-translation-quality.py \
  docs/roadmap/interfaces/operational-diagnostic-conversations-ko.md
```

## Related docs

| To learn about | Read |
|----------------|------|
| Acceptance contract | [Operational diagnostic conversations](../../roadmap/interfaces/operational-diagnostic-conversations.md) |
| Korean contract | [Operational diagnostic conversations (Korean)](../../roadmap/interfaces/operational-diagnostic-conversations-ko.md) |
| Existing planner boundary | [Hierarchical conversation planning](../../roadmap/interfaces/hierarchical-conversation-planning.md) |
| Existing document boundary | [Production A3 channel runtime](../../roadmap/interfaces/production-a3-channel-runtime.md) |
