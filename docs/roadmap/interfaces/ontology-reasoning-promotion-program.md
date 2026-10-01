---
title: Ontology Reasoning Promotion Program
---
# Ontology Reasoning Promotion Program

This document designs how the question-form compiler moves from shadow to production answers. It
covers the evidence that models may see, production shadow wiring, the direction readers, verified
answer authoring, the live validation program, promotion and removal, the one open Owner decision,
and the order of all remaining reasoning work. It extends the
[Ontology Reasoning Compiler](ontology-reasoning-compiler.md) and follows its
[delivery rounds](ontology-reasoning-compiler.md#delivery-rounds).

> **Status:** Proposed design, 2026-10-01. Delivery state and remaining work live in the
> [implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-promotion-program.md).
> Every live model, Azure, or SRE Agent run needs an explicit Owner request.

## Design at a glance

Promotion turns one operation family from observation into enforcement, so the compiled path
answers production turns for that family. In shadow mode, the compiler observes and records
dispositions but doesn't change answers. Promotion happens only on receipts measured from
production shadow turns and repeated live rounds, never from local experiments.

| Package | Delivers | Round |
|---------|----------|-------|
| P0 Model evidence view | The only evidence projection any model may read | Before P2 and P3 |
| P1 Production shadow wiring | The form carried in the judgment call, a turn reservation, and a linked disposition for every turn | R3 to R8 |
| P2 Direction readers | The complete direction majority protocol in production composition, with latency and cost | R5 |
| P3 Verified answer authoring | Claims under the shared proposition contract, full V-CLAIM, and an independent entailment review | R8 |
| P4 Validation program | Baselines, per-wave validation, and final promotion evidence | R0 to R9 |
| P5 Promotion and removal | Promotion and parity receipts per family, then removal of lexical re-derivation | R9 and R10 |
| P6 Secret detection decision | An Owner decision on secret detection in operator-typed model input | Wave 0 |

## P0 Model evidence view

Every model call that reads evidence, the answer author, the entailment reviewer, and any reader,
receives a `ModelEvidenceView` built by the secured gateway, never raw tables.

- The view holds only allowlisted cells. For links, it holds the reviewed link-evidence allowlist
  of approved decision 7: `verified`, `verification_method`, authority, effective time, freshness
  ceiling, and completeness.
- A hidden endpoint never appears, even when a visible link points to it. Provider bodies, handle
  metadata, and retained snapshot cells are excluded.
- The view carries digests of the deployment scope, authority, temporal basis, completeness,
  release, and the verifier that built it, so a claim can cite exactly what the model saw.
- Local implementation routes adaptive evidence reads through this view before model input. Until
  the Owner approves model families for P0, the proposed default is that no model family may read
  the view in production.

**Exit:** tests show that hidden endpoints and non-allowlisted fields never reach any model call,
and the Owner approves which model families may read the view.

## P1 Production shadow wiring

Promotion evidence comes only from the form carried as an additive field of the existing judgment
call. A tap that makes its own model calls beside a turn measures a different reading, so its
records stay an experiment.

- **Carry:** The judgment contract gains the closed form as an optional field under a new minor
  version. A missing or invalid form is a typed `form_absent` disposition, and the answer is
  unchanged.
- **Budget:** The shadow reserves from its own capacity under the
  [turn budget reservation](ontology-reasoning-coverage-expansion.md#e5-turn-budget-reservation),
  so it never charges or cancels the answer's budget.
- **Conditions:** The wiring meets every condition in the owner design's production shadow wiring
  paragraph: fresh anchor cutoffs, drained cancellation, a sanitized context, fan-out that stops on
  HTTP 429 or 503, one observed utterance per turn, the executor's scope digest, keyed sample
  identifiers, a durable sink, and a typed setting that defaults to off.
- **Linked records:** Each disposition links content-free digests of the keyed sample identifier,
  the judgment request, the carried form, the prompt, model, and configuration, the manifest and
  cutoff, the compiled plan, and the answer output. That link proves the evidence came from the
  carried form.
- **Non-interference:** The shadow has no data path into answer composition, and a module-boundary
  test enforces it. Replaying the same request and snapshot inputs with the shadow on and off
  yields identical answer digests.
Local implementation carries the closed form on the judgment contract under schema `1.4.0`, exposes
it to the judgment model only behind a default-off setting, and records linked content-free
dispositions through an injected production-shadow sink. Missing or invalid forms record
`form_absent` without changing the answer path. Every judgment recovery path validates the carried
form the same way, so an invalid form can't disable a recovery that accepts the same judgment
without it. The sampled production window remains live promotion evidence.

**Exit:** a linked disposition for every eligible turn over a sampled production window, and replay
equivalence with the shadow on and off.

## P2 Direction readers

A disputed relation direction is settled by the owner design's majority protocol, not by one
reader:

1. A blind binary reader of another model family than the proposer reads the question and both
   directions in a fixed order, from masked, minimal input.
2. When it disagrees with the proposer, a second blind reader of a third family decides.
3. The direction stands only when two concrete readings agree. Otherwise, or on a timeout or an
   unavailable reader, the turn holds with a typed reason.

Production composition binds both readers through the resolved model manifest under the provider
budget. Each directional turn records latency and token cost, split between one-reader and
two-reader turns.

**Implementation note (2026-10-01):** Every shadow turn now carries a content-free direction cost
receipt, and logs it as `semantic_direction_cost`. The receipt counts one or two readers, with the
calls, input bytes, output tokens, and wall time that the turn's reservation ledger reconciled.
Production composition also binds the direction reader and third-family tiebreaker when the P1
production shadow setting is on, but keeps compiled answers disabled outside the local venue.

**Exit:** both readers run in the production composition, and a latency and cost receipt covers a
sampled production window for each turn type.

## P3 Verified answer authoring

Bragi's T1 author writes every answer from the admitted form and the P0 view, with per-goal
statuses and typed limitations, and returns structured claims, as the owner design's
[answer composition](ontology-reasoning-compiler.md#answer-composition) defines.

1. **One proposition schema:** The author, V-CLAIM, and the reviewer share one canonical
   proposition model in the service contracts, with every owner-design field, including the
   quantifier, unit and currency, temporal basis and time zone, modality, and causal class.
2. **V-CLAIM:** Deterministic checks compare every proposition with its evidence through canonical
   identities. They reject a missing reference, a changed or undeclared literal, a wrong count, an
   unaccounted row, a missing limitation, a missing required goal or form atom, and a cause without
   a causal-grade receipt.
3. **Entailment review:** An independent T1 reviewer of another model family checks that each claim
   follows from its cited evidence. A rejection regenerates once with typed reasons. A second
   rejection holds the answer with the verified evidence view.
4. **Adversarial suite:** One test class per proposition field and per completeness check, plus
   negated, swapped, off-by-one, and causal-overreach claims.
Local implementation provides the shared proposition contract, default-off author and reviewer
ports, and the deterministic adversarial V-CLAIM suite. Production model-family bindings and the
R8 live holdout remain promotion evidence, not local proof.

**Exit:** zero escapes on the adversarial claim suite, and zero V-CLAIM escapes in the R8 holdout.

## Validation program

Live runs measure behavior that local tests can't prove. Each run has total, stage, and
no-progress deadlines. It stops on an unexpected T2 fallback, HTTP 429 or 503, or a provider
timeout, and it keeps only redacted, content-free receipts. The program has three phases:
baselines in Wave 0, validation after each wave, and final promotion evidence in Wave 5.

| Measure | Rule | Exit |
|---------|------|------|
| R0 baselines | L1 with two repeats, L2 on the fixture graph, and the Azure SRE Agent parity baseline over the reasoning cohort | Retained L1, L2, and parity receipts |
| L1 coverage | Recover from 84 of 120 runs without a released over-compilation | At least 105 of 120 across two repeated rounds |
| Released wrong answers | A compiled and released answer whose executed rows differ from the gold rows counts in every round | Zero in every L1 round; any occurrence is a defect |
| Release variance | Three repeated 20-question rounds for the deallocated VM, recent change, and containing-group questions | All three answer in every round |
| Long conversations | The same questions in a fresh context and late in a 20-turn context | Equal verified answers across two repeats |
| Traced exits | Compiled-plan coverage, terminal clarification, and ambiguity-reader rounds | Each traced question meets its ledger exit |

## P5 Promotion and removal

Promotion is per operation family, through the promotion registry, in this order:

1. The family's coverage lanes record their exits in the
   [coverage ledger](../../roadmap-implementation/interfaces/ontology-reasoning-coverage.md).
2. The family meets the owner design's bar: hard zeros on every repeat and on sampled shadow turns,
   the holdout floor, a gap of 5 points or less between English and Korean, no p95 latency rise,
   SRE Agent parity, and no regression in the 68-case corpus.
3. The registry records one promotion receipt and one parity receipt, and the family's frame and
   plan prompts retire.
4. Rollback restores the previous registry entry. The current path stays intact until R10.

R10 removes lexical re-derivation and template renderers only from promoted paths, after replay
equivalence and one stable rollback release.

**Hardening note (2026-10-01):** Critique rounds tightened P1 and P2 before any promotion. A shadow
record that fails to persist is logged and never changes the answer, and each record has its own
key. The carried form stays out of the frame model's input, and a judgment at schema 1.3.0 or 1.4.0
keeps its document query. The judgment schema sent to the model drops the definitions a disabled
field no longer references. The direction cost receipt measures latency as a span, counts only
settled usage, and counts a second reader only when a tie-break call was sent.

## P6 Secret detection decision

Operator-typed text reaches models after identity masking, and pattern-based detection removes
secret-shaped strings on a best-effort basis. P2 and P3 add model families that read operator text
and evidence, so the Owner decides before Wave 4:

| Option | Consequence |
|--------|-------------|
| Replace the patterns with a reviewed detector | A new dependency and its review; the encoded-shape regression suite must pass against it |
| Accept the patterns as defense in depth for the in-tenant model deployment | The decision records that the deployment boundary is the primary control |

**Exit:** the decision is linked from the ledger, and the encoded-shape regression suite in
`test_semantic_reasoning_masking.py` passes against the chosen detector.

**Decision (2026-10-01):** The patterns stay as defense in depth for the in-tenant model deployment,
and the deployment boundary is the primary control. This option was adopted under the Owner's
instruction to implement all waves, because a replacement detector would add a dependency that
needs its own supply-chain review. The Owner can revise it before any model family reads
operator text in production.

## Sequencing

Remaining reasoning work runs in six waves. A wave starts only when the waves it depends on have
their exits, and every package keeps its own exit. Validation runs after each wave.

![Sequencing. The main stages are Wave 0: R0 baselines, P6 decision, P0 evidence view, Wave 1: H1 contracts, H3 property lookup, E5 reservation, E7 readers and domains, Wave 2: H2 handle store, E1 slots, E6 lineage, H5 change continuation, Wave 3: H4 ordinals, E2 provenance, E3 relations, E4 routing, H6 plans, E9 operators, Wave 4: P1 shadow, P2 readers, P3 verified answers, then E8 hypotheses, Wave 5: final evidence, P5 promotion, then removal.](../../diagrams/generated/fdai-roadmap-interfaces-ontology-reasoning-promotion-program-01.en.svg)

Documentation follows the same structure. The owner design stays the normative contract for the
form, the checks, and the delivery rounds, and new work lands in the focused designs. After the
first family is promoted, the owner design's typed-only, causal context, and review sections move
into their own focused documents, so the owner returns within the roadmap document size limit.

## Remaining-work map

Every open item that the compiler ledger held on 2026-10-01 now has one owner package, and its
text moved to that package's ledger.

| Former compiler ledger item | Owner |
|-----------------------------|-------|
| R1 handle, evidence-manifest, and pushdown contracts | [H1](ontology-reasoning-result-handles.md#h1-contracts) |
| Persist result handles with the durable Operator turn | [H2](ontology-reasoning-result-handles.md#h2-handle-store) |
| Property of a named resource and the ordinal SKU follow-up | [H3](ontology-reasoning-result-handles.md#h3-property-follow-ups) and [H4](ontology-reasoning-result-handles.md#h4-ordinal-follow-ups) |
| Change-list continuation | [H5](ontology-reasoning-result-handles.md#h5-change-continuation) |
| All-kinds neighbourhood as successive plans | [H6](ontology-reasoning-result-handles.md#h6-successive-relation-plans) |
| Typed constraint slots | [E1](ontology-reasoning-coverage-expansion.md#e1-typed-constraint-slots) |
| R2 interim operand provenance | [E2](ontology-reasoning-coverage-expansion.md#e2-operand-provenance-through-binding-receipts) |
| Relation questions on the current path and the T2 state review | [E3](ontology-reasoning-coverage-expansion.md#e3-relations-on-the-current-path) |
| Standalone questions in long conversations | [E4](ontology-reasoning-coverage-expansion.md#e4-standalone-questions-in-long-conversations) |
| Schema form and frame budget | [E5](ontology-reasoning-coverage-expansion.md#e5-turn-budget-reservation) |
| Grouping by container kind | [E6](ontology-reasoning-coverage-expansion.md#e6-grouping-by-container-kind) |
| Health lookup, state history, and lifecycle domains | [E7](ontology-reasoning-coverage-expansion.md#e7-single-target-health-state-history-and-lifecycle-domains) |
| Causal change points | [E8](ontology-reasoning-coverage-expansion.md#e8-causal-change-points-and-evidence-grades) |
| R3 to R8 round exits | This program, with [E9](ontology-reasoning-coverage-expansion.md#e9-remaining-operators-and-relation-senses) for the operators |
| Production shadow wiring | [P1](#p1-production-shadow-wiring) |
| Direction reader deployment | [P2](#p2-direction-readers) |
| Answer author, V-CLAIM, and entailment review | [P3](#p3-verified-answer-authoring) |
| R0, L1 coverage, released wrong answers, variance, compiled-plan coverage, terminal clarification, and ambiguity rounds | [Validation program](#validation-program) |
| R9, R10, and coverage-lane exits | [P5](#p5-promotion-and-removal) |
| Secret detection decision | [P6](#p6-secret-detection-decision) |

## Decisions requiring approval

1. Production shadow telemetry goes to the existing durable decision-event sink, keyed and
   content-free (proposed), rather than a new store.
2. Promotion uses the owner design's bar unchanged (proposed), and any stricter floor is recorded
   per family in the coverage ledger.
3. The model families that may read the P0 view, and the P6 option.

## Critique and revisions

An independent critique of the first draft found the following issues. This design includes each
revision.

| Finding | Revision |
|---------|----------|
| The proposition and V-CLAIM contracts were weaker than the owner design | One shared proposition schema with every field, and V-CLAIM checks for undeclared literals and missing goals or atoms |
| One direction reader can't settle a disputed direction | The complete majority protocol with a third-family reader and typed holds |
| The wave order violated dependencies | R0, P6, and P0 form Wave 0; ordinals follow the handle store; E8 hypotheses follow P3; validation runs after every wave |
| No model-safe evidence projection existed | P0 builds the only view any model reads, with the link-evidence allowlist and hidden-endpoint suppression |
| Shadow evidence couldn't prove its origin or non-interference | Linked content-free digests, a module-boundary test, and replay with the shadow on and off |
| Several R3 to R8 capabilities had no owner | E9 and the remaining-work map give every item one owner |
| The linked ledger didn't exist | The ledger exists and owns this document's remaining work |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-promotion-program.md) |
| The compiler, its checks, and the delivery rounds | [Ontology Reasoning Compiler](ontology-reasoning-compiler.md) |
| Handles and continuations | [Result Handles and Continuations](ontology-reasoning-result-handles.md) |
| Compiler coverage and current-path work | [Coverage Expansion](ontology-reasoning-coverage-expansion.md) |
| Coverage lanes and the parity bar | [Ontology Reasoning Coverage](ontology-reasoning-coverage.md) |
