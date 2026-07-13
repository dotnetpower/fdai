---
title: Manual Distillation
---
# Manual Distillation

How FDAI absorbs an adopting company's **operational and deployment manuals** by
*compiling* them into deterministic rules, workflows, and policies at build time,
rather than *retrieving* from them at runtime with RAG. This document answers:
*how does a prose manual become an executable T0/T1 artifact, and how do we verify
the distillation is faithful before it can act?*

It complements - and does not restate - the source-collection mechanics in
[rule-catalog-collection.md](rule-catalog-collection.md), the authoring / scoping /
promotion model in [rule-governance.md](rule-governance.md), and the quality-gate
and living-rules principles in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).
The continuous pipeline it plugs into is
[phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md).

> **Customer-agnostic scope (MUST).** A company's manuals are customer data. The
> manuals themselves, and every rule distilled from them, live in the **downstream
> fork**, never in this repo (see
> [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)
> and [downstream-fork-guide.md](../fork-and-sequencing/downstream-fork-guide.md)).
> Upstream ships only the generic **distillation mechanism** (a collector kind plus
> the verification pipeline). Every example below uses synthetic placeholders.

## Why compile, not retrieve

RAG answers a manual question at runtime: embed the query, retrieve chunks, let an
LLM read and interpret them. That path is **probabilistic, ungrounded by default,
and re-decided on every event** - which FDAI accounts as T2 (frontier-model) cost.
Operational and deployment manuals are mostly **repeatable procedures, thresholds,
and decision trees**, so routing them through T2 on every event contradicts the
`deterministic-first` principle (target: LLM inference at ~5-10% of events).

Compilation instead pays the LLM cost **once, offline**, turning the manual into
versioned deterministic artifacts that the T0/T1 tiers evaluate for free and that
carry an audit trail. RAG is not removed; it is demoted to a residual role (see
[Where RAG remains](#where-rag-remains)).

| | RAG (retrieve) | Distillation (compile) |
|---|---|---|
| When the LLM runs | every event (runtime) | once, at build time |
| Tier | T2 | T0 / T1 |
| Determinism | re-decided per query | fixed, versioned artifact |
| Grounding | best-effort | `provenance` mandatory or reject |
| Audit / rollback | none by default | catalog versioning + PR |

## What gets compiled

A manual is not one artifact kind. Distillation decomposes it by the shape of each
statement and routes each fragment to the matching slot:

| Statement in the manual | Compiled target | Home |
|---|---|---|
| Judgement criteria, thresholds, "must not" conditions | **Rule / policy** | [rule-catalog catalog](rule-catalog-collection.md), OPA/Rego |
| Ordered procedure (restart / scale / roll back) | **Workflow** (runbook-as-code) | [rule-catalog/workflows](../../../rule-catalog/workflows/) |
| A single thing that mutates state | **ActionType** (with `rollback_contract`) | rule-catalog action-types |
| Deployment procedure, environment spec | **IaC + policy-as-code** | Terraform + deployment gate |

Each fragment normalizes to the same schema the rest of the catalog uses and shares
one `provenance` stamp (manual URL + section + content hash). Mechanically, an
adopting company's manual is just a new **collection source** in the taxonomy of
[rule-catalog-collection.md](rule-catalog-collection.md#collection-sources): a
"customer-authored operational / deployment manual" group whose collector is the
distiller described below.

## The distillation pipeline

Offline, build-time, and staged behind the same gate every rule candidate passes.
No fragment reaches the enforcing catalog on the strength of the model alone.

```text
manual (PDF / wiki / docs)
  -> ingest + chunk (build time)
  -> LLM extract candidates  (rule | workflow | action-type | policy) + provenance
  -> source-fidelity gates   (grounding, back-translation, mixed-model)
  -> structural gates        (schema load, safety-invariant check)
  -> shadow evaluation       (replay against real history)
  -> regression + human promotion PR
  -> enforce
```

Step 2 is the only place an LLM runs, and it runs **once per manual revision**, not
per event. Everything after step 2 is deterministic verification plus a human gate.

## Verifying the distillation

A distilled fragment can be wrong in five distinct ways. Verification is layered so
each mode has an owner:

| Failure mode | Example | Caught by |
|---|---|---|
| Hallucination | a rule not present in the manual | grounding gate |
| Misread | `>80%` compiled as `>=80%`, inverted logic | back-translation, mixed-model |
| Incomplete | a rule the manual states was never extracted | coverage diff (residual) |
| Conflict | contradicts an existing catalog rule | dedupe + precedence |
| Unsafe | an action with no rollback / stop-condition | schema + verifier |

The key idea: **the manual text is the ground truth for "did we read it right", but
the company's real operational history is the ground truth for "does this fragment
act correctly".** Verification therefore has two prongs.

### Prong A - source fidelity ("did we read the manual right")

- **Grounding gate (blocks hallucination).** Every candidate MUST cite the exact
  manual section it derives from. No citation -> reject and abstain. This is the
  architecture's grounding rule (`abstain when unsupported`) applied to distillation.
- **Back-translation round-trip (blocks misread).** A *different* model regenerates
  a natural-language description from the compiled YAML; the result is diffed against
  the original passage. A semantic mismatch flags the candidate. Compile -> decompile
  -> compare is the distillation-specific check that catches threshold and polarity
  errors.
- **Mixed-model cross-check (blocks misread).** The extraction runs on 2+ distinct
  models; disagreement on a threshold or condition escalates to HIL rather than
  auto-accepting. This is FDAI's mandatory mixed-model gate - distillation is a T2
  judgement and obeys it.

### Prong B - reality fidelity ("does the fragment act correctly")

- **Schema + verifier (blocks unsafe / malformed).** The candidate must load against
  the rule / workflow / action-type schema, and every action must carry the four
  safety invariants (`rollback_contract`, stop-condition, blast-radius, audit).
  A miss fails at load, not at first dispatch.
- **Shadow-mode replay (the empirical proof).** The fragment runs `default_mode:
  shadow` against the company's **real historical events and audit log**. Did it fire
  when the manual says it should have? Do its shadow verdicts match what operators
  actually did? Precision / recall are measured - not "the text looks right", but "it
  behaves right on real data". This is the `promotion_gate`.
- **Regression suite (zero escapes).** Known manual scenarios become golden tests;
  the fragment must pass with zero policy-violation escapes, and every rule change
  adds a regression test.

Promotion to enforce is never automatic: measured shadow accuracy -> explicit
human-approved PR, following the same `collect -> shadow -> regression -> promote`
order documented in [rule-catalog-collection.md](rule-catalog-collection.md) and
[phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md).

## Residual risk: false negatives

The gates above verify **the fragments that were extracted**. They cannot verify a
rule the manual states but distillation **never extracted** - a fragment that does
not exist has nothing to replay. This coverage gap (false negatives) is the honest
limit of distillation and cannot be fully automated away. It is mitigated, not
eliminated:

- **Structural coverage diff.** Count the manual's section headings and imperative
  statements ("must", "must not", "shall"), compare against the extracted-fragment
  count and topics, and flag uncovered sections for human review.
- **Operational feedback.** When shadow runs a stretch with no rule firing yet a real
  incident occurs, that gap is a missing-rule signal the discovery loop turns into a
  candidate (see [observability-and-detection.md](observability-and-detection.md) and
  the living-rules loop in
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).

"The manual was distilled completely" is reported as a measured coverage number with
human sign-off, never asserted.

## Where RAG remains

Distillation does not delete retrieval; it scopes it. Narrative knowledge that does
not compile cleanly (incident post-mortems, team conventions, rationale prose) stays
as citation chunks that the **T2 quality gate grounds against**. The primary path is
the compiled deterministic artifact; RAG is the residual T2 grounding backup, and
when it cannot cite support the tier abstains to HIL. A structured
knowledge-graph retrieval (over the existing PostgreSQL state store, no new service)
is preferred over flat vector RAG when relationship traversal matters.

## Open decisions

- **Chunking + extraction prompt** for each manual format (PDF vs wiki vs Markdown)
  is fork-supplied config, versioned like any other prompt.
- **Coverage-diff heuristic** (what counts as an "imperative statement") needs
  tuning per manual style; start conservative and human-review the flags.
- **Manual-source cadence**: how often the watcher re-distills a changed manual
  revision reuses the source-watcher cadence model from
  [rule-catalog-collection.md](rule-catalog-collection.md); a manual revision bumps
  the content hash and re-enters the pipeline.

## Next steps

| To learn about | Read |
|---|---|
| Where rules come from and their YAML shape | [rule-catalog-collection.md](rule-catalog-collection.md) |
| Authoring, scoping, exemption, promotion | [rule-governance.md](rule-governance.md) |
| Runbook-as-code workflow schema | [rule-catalog/workflows](../../../rule-catalog/workflows/) |
| The continuous quality + T1 pipeline | [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md) |
| Where customer manuals and rules live | [downstream-fork-guide.md](../fork-and-sequencing/downstream-fork-guide.md) |
