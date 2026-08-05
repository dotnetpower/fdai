---
title: Root-Cause Analysis
description: How FDAI produces tiered, cited root-cause hypotheses and holds for review when evidence is insufficient.
---

# Root-Cause Analysis

Root-cause analysis (RCA) explains why an incident may have happened. FDAI
stores RCA as a hypothesis with citations, confidence, tier, and evidence check
state. It is evidence for a decision, never permission to execute a change.

## RCA by trust tier

| Tier | Role | Typical evidence |
|------|------|------------------|
| T0 | Direct deterministic cause | Matched rule, violated control, declared fix |
| T1 | Prior-incident reuse or deterministic causal chain | Resolved incident, ordered change and symptom events, resource dependencies |
| T2 | Grounded reasoning for novel or ambiguous cases | Vouched telemetry, events, rules, knowledge chunks, scenario evidence |

T1 reuse re-verifies the prior cause and learned action against current
evidence. A T1 causal chain requires a preceding change as its root; a window
containing only symptoms holds for review instead of inventing a cause.

If reuse fails re-verification, FDAI does not replay the learned action. It can
try a configured T2 reasoner with the current evidence set or hold for human
review. Either path records why T1 was rejected, so a similarity hit cannot hide
stale scope, changed dependencies, or a superseded fix.

## Evidence check gate

Every citation must come from the evidence set supplied to the reasoner. A
malformed response, fabricated citation, unsupported claim, or confidence below
the configured threshold becomes an held for review hypothesis and routes to human
review.

Telemetry and operator documents are untrusted inputs. Model text cannot
override policy, what-if results, or the deterministic verifier.

Confidence comes from verifier, cross-check, and evidence check signals rather than
the reasoner's self-reported confidence. The T2 quality gate requires
independent cross-checking, deterministic verification, and citations that
resolve inside the supplied evidence allowlist. A rubric or cross-check can
only lower eligibility; it cannot rescue an unsupported candidate.

| RCA outcome | Stored result | Response path |
|-------------|---------------|---------------|
| Grounded and above configured threshold | Hypothesis with citations | May inform a typed proposal |
| Ambiguous alternatives | Capped-confidence hypothesis | Human review |
| Stale T1 reuse | Rejected reuse with provenance | Current-evidence T2 or human review |
| Malformed or fabricated citation | Held for review hypothesis | No action; audit and review |

## Causal chains

A structured T1 chain preserves root and failure event IDs plus ordered hops.
Each hop records cause and effect references, lead time, relationship, and
confidence. Resource dependency data strengthens related paths and blocks
unrelated links when a graph is available.

Temporal order alone is not certainty. Confidence is bounded, reduced when
multiple roots explain the failure similarly, and determined by the weakest
supported link.

## How strong is the causal claim

A cited hypothesis still varies enormously in strength. FDAI grades that strength explicitly, so
"we think the deployment did it" and "we removed the deployment and the errors stopped" don't read
the same.

| Grade | What it rests on | What it can support |
|-------|------------------|---------------------|
| Association | Things happened close together on a related resource | Explaining and choosing the next investigation |
| Predictive precedence | The candidate repeatedly precedes the effect and predicts its direction | A recovery proposal in observation mode or with explicit approval |
| Quasi-experimental | A comparable untreated group behaved differently | Bounded recovery eligibility when every other safety check passes |
| Interventional | An approved intervention reproduced or removed the predicted effect | Promotion evidence, and never permission on its own |

Two mechanisms keep a grade honest. A chain is scored by its weakest link, so one unsupported hop
collapses the whole claim rather than averaging out. And every supporting query is paired with a
refutation query: if the hypothesis says errors rose after the deployment, FDAI also asks whether
unchanged hosts saw the same rise beforehand. A missing refutation is recorded as unknown, not as
support.

When refuting evidence arrives, the hypothesis is marked refuted or dropped to a lower grade and a
new revision is written rather than the old one being edited. A decision already made isn't silently
rewritten, but future autonomy can drop if the grade no longer clears the bar policy requires.

Closure is the terminal state after an intervention: confirmed, refuted, inconclusive when the
outcome evidence was stale or incomplete, or unsafe when the observed impact went past what was
approved. Closure is evidence about the hypothesis. It grants no execution permission, skips no
safety check, and a confirmed hypothesis with an unsafe impact moves both the hypothesis and its
related action back to observation mode.

> **Current status:** The hypothesis lifecycle, weakest-link scoring, support and refutation links,
> temporal analysis, and independent closure classification are implemented. The control loop
> analyzes and audits in observation mode rather than writing causation into the ontology, and a
> deployment binds its own temporal series, projection publisher, outcome provider, and receipt
> resolver. No causal result grants execution.

## Read an RCA dossier

Check these elements together:

1. Incident and correlation ID.
2. Tier, outcome, confidence, and evidence check state.
3. Citations and evidence freshness.
4. Alternative or ambiguous hypotheses.
5. Structured causal hops when present.
6. Linked response plan, decision, mode, and rollback reference.

Missing chain data or evidence renders unavailable. The browser does not
reconstruct a more confident explanation than the audit record contains.

## Next steps

| To learn about | Read |
|----------------|------|
| How evidence is bounded | [Triage and investigation](triage-and-investigation.md) |
| How a mitigation is proposed | [Response plans and mitigation](response-plans-and-mitigation.md) |
| How decisions are audited | [Read the audit log](../guides/read-audit-log.md) |
| The detailed RCA contract | [Observability and Detection](../../roadmap/rules-and-detection/observability-and-detection.md) |
