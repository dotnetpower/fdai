---
title: Governed Typed Selection Read
---
# Governed Typed Selection Read

This design owns the bounded async model stage, immutable read evidence, and governed capability
binding for typed instance answers. It implements the selected A boundary of #2275 under #2034
and #2256, not activation or a claim that the current model is qualified.

> The existing deterministic, network-free, five-second candidate Function remains unchanged.
> Hosted inference is neither deterministic nor seed-reproducible. No model call runs inside
> the ordinary Function registry.

## Design at a glance

| Stage | Owner and boundary | Required output |
|-------|--------------------|-----------------|
| Qualification admission | Independent verifier, judged by Forseti | Exact source/model/prompt/policy/scope-bound qualified artifact; unavailable or failed means held. |
| Human approval | Var, existing typed approval lifecycle | Exact immutable request and attributed current approval. |
| Promotion | Thor, registered governance ActionType | Durable CAS read-capability pointer; approval finalization gates use. |
| Model read | Bragi-owned async read preparation before Function invocation | At most two calls, each at most 20 seconds, under one 24-second deadline. |
| Evidence consumption | Deterministic versioned Function | Exact single-use principal/query/source/model/revision/expiry evidence plus current secured membership. |
| Demotion | Vidar, typed revocation/regression and scripted rollback | Higher disabled revision and a permanent withdrawn-qualification fence. |
| Audit | Saga, existing intent/terminal audit | Attributable promotion, refusal, and demotion. |

## Authority and evidence

The read pointer starts disabled. Its binding identifies exact code revision, ontology manifest,
principal scope, model/request/prompt identity, context protocol and data-handling policy.
Qualification is admitted independently for that exact binding; a caller's boolean is not a gate.
The current raw embedding qualification failed and the previous Sol pin cannot qualify the mini.

Promotion uses the existing exact-review attestation and typed Forseti/Var/Thor/Saga lifecycle.
An approved label, model name, dispatched request or old success receipt cannot grant answer use.
Revocation or regression lowers authority through Vidar. An old promotion cannot cross the higher
revision fence or reuse a withdrawn qualification.

## Selected A execution boundary

The production Function-node handler prepares read evidence before invoking the ordinary registry.
The model stage sees the complete source-safe context and verifies agreement before persisting
immutable evidence. Cancellation, disagreement, unavailable qualification, expired evidence or
source/model drift produces a held result and no consumable evidence.

The new deterministic Function performs no model call. It checks the current pointer and exact
principal, query, source, model, code revision and expiry again, verifies current secured membership,
and consumes the evidence once. Demotion between preparation and consumption therefore wins.
Results remain candidate-only, non-exhaustive and carry no execution authority. Raw vector ranking
is not enabled, and the existing 500-total-enum and 1,000-row membership limits remain explicit.

## Pre-implementation critique and revision

The reviewed hypotheses are: hidden network calls inside Function; confusing progress with
authority; fake seeded inference; calls before qualification; source/model drift during calls;
cancellation producing evidence; replay across requests; expired or naive clocks; concurrent
demotion; direct approval bypass; rollback resurrecting old authority; and role/schema shortcuts.

Revision: use the existing pre-Function handler and exact-review dispatcher, preserve the ordinary
runner rejection of network/credentials, and bind the evidence to the authoritative pointer revision.
No new execution class, role owner, or implicit qualification is introduced.
The initial 45-second stage proposal was narrowed to 24 seconds so preparation plus the five-second
deterministic Function fits the existing 30-second query-node ceiling. Sibling calls cancel together.

## Related docs

| To learn about | Read |
|----------------|------|
| Parent query contract | [Ontology Query Coverage Implementation Plan](ontology-query-coverage-implementation-plan.md) |
| Implementation and remaining gates | [Implementation ledger](../../roadmap-implementation/interfaces/governed-typed-selection-read.md) |
