---
title: Post-Turn Improvement Review
---

# Post-Turn Improvement Review

This design defines how FDAI reviews a completed operator conversation outside the request path
and produces an inert improvement proposal. It covers consent, evidence bounds, agent ownership,
mixed-family review, durable deduplication, governed routing, and read-only operations.

> **Scope:** The review proposes operator memory, runtime skills, or rule hints. It never changes
> runtime behavior, grants authority, approves its own output, or delays the completed response.
## Design at a glance

Bragi publishes one bounded completed-turn envelope on `object.post-turn-review`. Norns,
the learner, applies deterministic eligibility and optionally asks two distinct model families for
the same typed proposal. Exact agreement can create a draft in the subsystem that owns the target
artifact. Every other outcome becomes a bounded terminal record.

![Design at a glance. The main stages are Persist completed turn, Bounded non-blocking queue, Bragi publishes object.post-turn-review, Norns checks eligibility, Durable terminal record, Two distinct model families, Exact agreement and deterministic checks, Operator-memory draft, Runtime-skill draft, Norns RuleCandidate path, Read-only projection.](../../diagrams/generated/fdai-roadmap-decisioning-post-turn-improvement-review-01.en.svg)

## Input contract

`PostTurnReviewInput` is a bounded projection, not a transcript or process snapshot. It includes:

- Stable review, operator-turn, assistant-turn, and principal-scope identifiers.
- Completion time and safe evidence references.
- Tool name, status, and evidence reference for each tool receipt. Raw tool output is excluded.
- Validation outcomes, recovered-failure status, and an optional repeated
  procedure fingerprint.
- Optional operator and assistant bodies and explicit correction text only when the principal has
  `share_with_learner: true`.
- Optional operator-memory scope only when both scope kind and scope reference are known.

Identifiers, body length, tuple counts, timestamps, and scope pairs are validated at construction.
Raw credentials, hidden reasoning, unrestricted process state, and unrestricted tool output are
not part of the contract.

Explicit corrections are raw text, not consent-free metadata. Bragi removes both bodies and
all corrections without a matching opt-in before creating an outbox checkpoint. Norns independently
requires complete bodies and matching recorded consent, scans all correction text for sensitive
content, and applies one 64 KiB UTF-8 budget to the bodies and corrections joined by newlines.
Correction text alone does not bypass the complete-body requirement.

Outbox recovery holds legacy raw-text rows without matching recorded consent instead of
republishing them. The hold preserves the original row and records a content-free behavior reason;
it does not prevent other valid rows in the selected recovery batch from being published. This
does not redact historical records or independently revalidate current consent after restart.

## Ownership and transport

Bragi remains the single writer of `object.post-turn-review`. Its typed publisher accepts only an
already validated, consent-filtered `PostTurnReviewInput`. The Operator API must submit to a bounded
queue that publishes an Operator-owned request; Core ingress calls the Bragi boundary. The Operator
does not instantiate a reviewer or label itself as Bragi or Norns.

Norns subscribes to consent-filtered `post_turn_review` envelopes on `object.post-turn-review`. It rejects an
envelope whose `producer_principal` is not `Bragi`, strictly parses the review mapping, and invokes
the injected coordinator off path. Norns gains no new owned topic and no execution authority.

Azure transport sends every Pantheon logical object topic through the configured physical object
topic with `MultiplexedEventBus`. The headless runtime and Operator API therefore share the same
logical-to-physical mapping. Process-local transport keeps the same logical contract without
inventing Azure evidence.
Production Operator composition now offers terminal answered semantic turns to a bounded
asynchronous post-turn queue, which publishes an Operator-owned
`operator.post-turn-review.requests` envelope through the configured semantic transport without
blocking turn projection. Core registers that request topic in its runtime logical topic set,
so it receives the multiplexed request on the semantic physical Event Hub instead of a raw hub that
does not exist. Core consumes that request, validates it, and invokes Bragi's typed
publisher so only Bragi writes `object.post-turn-review`.

## Recurrent-query observations

Core attaches a typed `PostTurnProcedureReceipt` to the technical details of a completed human
ontology query. Its fingerprint binds the exact ontology and semantic-catalog releases, purpose,
ordered DAG, canonical functions, and JSON argument types and structure. It excludes argument
values, question text, principal identity, and incidental node names. It compares executed shapes,
not the meaning of natural-language questions. Workloads, incomplete execution/evidence, and an
exceeded shape-depth budget carry an explicit unavailable reason instead of a fingerprint.

Operator checks the receipt against the authenticated principal, turn, release, plan, completed
checks, and execution digest. It ignores unverified fingerprint/count hints. The existing current
learner-sharing preference gates its queue; Bragi preserves typed metadata but still removes raw
text without matching body consent. Optional procedure metadata cannot overflow an existing
answer: Core omits only that metadata, records a content-free reason, and recomputes projection
identity. This neither truncates the answer nor turns metadata into eligible raw-body review.

Norns uses its existing durable StateStore to count distinct canonical principal scopes in
`(now - seven UTC days, now]`. The default threshold is five; the constructor accepts integers
from two through twenty. A stored/runtime threshold mismatch fails closed rather than resetting
evidence. One bounded, revision-fenced record holds at most 128 shapes. Expired shape state is
pruned on accepted observation updates; this is not a scheduled physical-deletion receipt.
Capacity exhaustion and corrupted state are explicit failures, not empty successful collections.

A qualifying cohort first becomes an immutable pending signal. Norns checkpoints the inert
candidate in its existing learner journal before acknowledging the source signal, so restart,
replica contention, and failed checkpoints can replay one stable identity. The signal uses
`source_signal=console.recurrent_query` on the existing `object.rule-candidate` input to Mimir,
not a new topic or an activated Rule. Counts describe the observed threshold cohort, not all
queries or all principals. Release digests and canonical tool names accompany bounded evidence
references without publishing principal identities or argument values.

The existing three-perspective consensus, rate limits, current discovery-activation ceiling,
Mimir review, and shadow promotion still apply. Norns health separates collection availability,
publication enablement, and inert mode. Missing durable storage remains unavailable. Local
component and isolated PostgreSQL checks do not qualify deployed transport, operational policy,
actual rule generation, or production stabilization.

## Eligibility

`PostTurnEligibilityPolicy` evaluates cheap deterministic signals before any model call:

| Signal | Eligible when |
|--------|---------------|
| Complex procedure | Tool-receipt count reaches the configured minimum. |
| Explicit correction | At least one bounded correction is present. |
| Recovered failure | A failure-to-success transition is recorded. |
| Repeated procedure | A stable fingerprint reaches the configured repetition threshold. |

Missing consent produces `opted_out`. Injection markers produce `unsafe_content`. A safe turn with
no qualifying signal produces `ineligible`. These outcomes are stored without calling a reviewer.

## Review and verification

The Azure adapter receives a catalog prompt and returns one strict JSON object. It uses temperature
zero, a bounded completion budget, audience-scoped workload identity, and no tool access.

`ConsensusPostTurnReviewer` accepts only exact agreement from at least two models with distinct
identities and distinct families. It then checks:

- Every proposal evidence reference is a subset of supplied evidence.
- Proposal text has no injection marker or secret-like content.
- Operator-memory scope exactly matches the supplied scope.
- Runtime-skill Markdown parses, and its manifest name matches the proposal name.

Missing model bindings, one-family resolution, model abstention, disagreement, unsupported
evidence, unsafe content, or schema failure produces `NoImprovement`. The runtime never degrades
the agreement requirement to one model.

## Governed routing

Accepted proposals stay behind the current owner workflow:

| Proposal | Owning path | Initial state |
|----------|-------------|---------------|
| `OperatorMemoryCandidate` | `OperatorMemoryProposalWorkshop` | `draft` |
| `SkillProposalDraft` | `SkillWorkshop` | `draft` |
| `RuleCandidateHint` | Norns `submit_rule_hint` then Mimir governance | inert hint/candidate |

The runtime authorizer denies review and materialization. A separately authenticated human path
must review the draft. Operator memory still requires a distinct approver. Runtime-skill promotion
rechecks publisher trust and installs disabled. Rule candidates still pass Mimir's quality and
promotion gates.

## Durability and idempotency

PostgreSQL stores the review ledger, proposal claim, operator-memory draft, and runtime-skill
draft. A stable review id prevents duplicate model calls after redelivery. A proposal key derived
from principal scope, proposal kind, procedure fingerprint, and evidence digest prevents two
replicas from creating the same draft.

Review state advances from `pending` to one terminal value:

- `ineligible`
- `abstained`
- `duplicate`
- `routed`
- `failed`

Compare-and-swap transitions preserve the first terminal outcome. Reviewer and router exceptions
become bounded `failed` reasons and do not affect the original conversation result.

## Read-only operations

The production panel `post-turn-reviews` reads the durable stores. It returns bounded row lists
for reviews, operator-memory drafts, and skill drafts, plus whole-store aggregate counts for:

- Eligibility, abstention, duplicate suppression, routing, and failure.
- Proposal kind and owner-workflow state.
- Operator acceptance over independently reviewed memory and skill drafts.

The projection omits proposal bodies and adds no approve, materialize, promote, or execute route.
Unavailable local or deployed data sources remain unavailable or empty; they are not replaced by
synthetic review records.

## Failure behavior

- Queue saturation drops review work without changing the response and records queue metrics.
- Retry is bounded and applies only to asynchronous intake failures.
- Missing reviewer bindings record `reviewer_unavailable`.
- Invalid or non-Bragi envelopes fail closed at the Norns boundary.
- Database conflicts preserve the winning review or proposal claim.
- Read projection failure does not change proposal state.

## Verification

Focused coverage includes eligibility signals, input bounds, consent, exact consensus, injection
and secret canaries, owner routing, non-blocking queue behavior, physical-topic multiplexing,
restart-safe PostgreSQL state, cross-replica proposal claims, read-only projection, and agent-role
layout. The repository gate remains `scripts/verify.sh`.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/decisioning/post-turn-improvement-review.md) |
| Pantheon ownership and topics | [Agent Pantheon](../agents/agent-pantheon.md) |
| Operator memory and runtime skills | [Prompt Composition](prompt-composition.md) |
| Consent and conversation persistence | [Operator Console](../interfaces/operator-console.md) |
| Local and deployed provider parity | [Runtime Parity](../deployment/dev-and-deploy-parity.md) |
