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

## Ingesting from siloed sources

The pipeline's first step (`ingest + chunk`) hides the hardest operational problem.
Real manuals do not arrive as a tidy folder of PDFs; they live in SharePoint,
Confluence, Notion, Loop, and email inboxes, each behind its own authentication, and
at a scale (thousands of pages) where most content is not a manual at all. Two
sub-problems fall out: **access without holding standing credentials**, and
**discovery plus triage at scale**.

### Access: push and delegate, do not hold standing credentials

The reframing that unlocks the auth problem: distillation is build-time and runs
**once per manual revision**, so FDAI never needs the continuous, broad read
credential a live search index does. The industry default (a service principal that
continuously crawls a whole tenant) triggers the exact admin refusal that blocks
adoption - `Sites.Read.All` over an entire tenant is rarely granted. Because the
access is one-shot-per-revision, the model can invert from *pull* to
*push / delegate*, and FDAI holds no broad standing credential:

| Mode | How | Standing credential FDAI holds | Best for |
|---|---|---|---|
| Drop / push | operator delivers the doc: a PR into the fork's manual folder, a console upload, or an email-in address | none | ad hoc, low volume, most sensitive |
| Designated space | one SharePoint library / Confluence space / Notion database the company blesses as the FDAI source; read scoped to that one location | one narrow, low-sensitivity scope | steady curated manuals |
| iPaaS trigger | a Power Automate / Logic Apps flow the enterprise already authenticated posts changed pages to an ingest webhook | none (the enterprise owns the auth) | auto-refresh on change |
| Delegated fetch | operator pastes a link in ChatOps; the narrator reads it with the operator's short-lived delegated (on-behalf-of / device-code) token | none standing | occasional, permissioned reads |

Prior art validates the split. Microsoft 365 Copilot connectors ship exactly two
shapes: **synced** connectors (index content into Microsoft Graph as an org-level
service that mirrors each item's ACL) and **federated** connectors (an MCP model that
fetches live per query with the user's own OAuth, indexing nothing). FDAI's sensitive
path mirrors the federated shape (delegated, no standing index); its bulk path
mirrors a designated, narrowly scoped synced shape. Building N bespoke connectors is
a known anti-pattern (the "DIY pipeline rat's nest"); prefer an existing ingestion
layer (Copilot connectors, an MCP connector server, or an ETL tool) that already
solved auth, delta sync, and 60+ file formats.

### Permission and sensitivity, not just authentication

Authentication ("can FDAI open the door") is only half the question. Two access
concerns a naive connector skips but distillation must answer:

- **Source ACL provenance.** Record *who was allowed to read* the source doc in
  `provenance`. A rule distilled from a restricted security runbook must not leak
  that runbook's text into an audit entry or a generated PR body - L0 stays English
  and secret-free
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- **Sensitivity gate.** A doc the service account *can* read may still be one it
  should not distill blindly: HR material, incident post-mortems naming customers, or
  runbooks with embedded credentials. Ingest runs a secret-scan plus PII-redaction
  pass, and a hit routes to HIL rather than auto-extracting.

### Discovery and triage at scale

At Confluence or Notion scale the problem stops being ingestion and becomes: which of
these thousands of pages *is* a manual? Most of a workspace is meeting notes, drafts,
and stale pages - distilling all of it explodes both cost and false positives. The
answer is FDAI's own tiering philosophy applied to the corpus: filter cheaply, compile
expensively, and only on a small subset.

1. **Free deterministic filters first** (T0-grade, no LLM). Labels
   (`runbook`, `sop`, `ops`), the source space / database, page-tree location, Notion
   "verified page" status, view count, and last-edited recency discard the dead long
   tail before any model runs.
2. **Cheap classifier next** (T1-grade). A small model or embedding classifier makes a
   binary "is this an operational procedure?" call on the survivors, narrowing
   thousands of pages to dozens or hundreds.
3. **Authority ranking.** The internal link graph surfaces canonical hub documents
   (PageRank-style) - brainstorming pages are linked by no one. Near-duplicate
   clustering keeps only the newest canonical version of a procedure.
4. **Priority queue, not big-bang.** Distill by operational signal: pages a recent
   incident actually referenced first (the living-rules feedback loop), then
   high-traffic pages, then the long tail. The most load-bearing manuals get covered
   first, automatically.
5. **Minimal human curation.** Rather than asking a company to organize thousands of
   pages, ask for one label (`fdai`) or run a batch "is this a manual? [yes / no]" HIL
   triage. Humans confirm O(dozens), never O(thousands).

Reuse the source's own curation instead of inventing one: Notion's **verified-page**
property (a workspace owner marks a wiki page verified, optionally with an expiry) and
Confluence labels / spaces are ready-made authority signals.

### Freshness and deletion propagation

Re-distillation reuses the source-watcher cadence from
[rule-catalog-collection.md](rule-catalog-collection.md): a changed page (Notion
`last_edited_time`, Confluence CQL `lastModified`, or Microsoft Graph change
notifications) bumps the content hash and re-enters the pipeline for the affected
fragments only, so a refresh is not a full re-crawl. The gap a naive sync misses:
when a source page is **deleted or archived**, the rules distilled from it must be
retired (tombstoned), not left firing on guidance the company has withdrawn. Deletion
is a first-class signal, handled like the living-rules retirement path in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

Deletion is not trusted blindly, though: an **empty listing over a non-empty
prior snapshot** is indistinguishable from a failed mount or an auth lapse, so it
is treated as a suspected source outage and fails closed - no retirements are
planned and the prior snapshot is preserved, so a transient outage never
tombstones the whole distilled catalog (a blast-radius limit on the deletion
path).

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

## Implementation status

The ingestion and verification mechanism ships upstream; the LLM-backed and
customer-connector parts are fork seams with abstaining defaults.

| Design element | Shipped as | Home |
|---|---|---|
| Access seam | `ManualSource` + `DropDirectoryManualSource`, bound by `bind_drop_directory_manual_source` | `shared/providers/manual_source.py` |
| Sensitivity guard | `scan_sensitivity` - value-free findings, `HOLD` -> HIL | `rule_catalog/pipeline/distill/sensitivity.py` |
| Triage (deterministic) | `triage_filter`, `dedupe_exact`, `authority_score`, `prioritize` | `rule_catalog/pipeline/distill/triage.py` |
| Classifier seam | `ManualClassifier` (abstaining default marks all `UNCERTAIN` -> HIL) | `shared/providers/manual_classifier.py` |
| Freshness + deletion | `diff_snapshot`, `plan_retirements` (tombstone) | `rule_catalog/pipeline/distill/freshness.py` |
| Coverage diff | `analyze_coverage` | `rule_catalog/pipeline/distill/coverage.py` |
| Compile seam | `Distiller` (abstaining default extracts nothing) | `shared/providers/distiller.py` |
| Orchestrator + CLI | `build_distillation_plan`, `distill_cli` | `rule_catalog/pipeline/distill/orchestrator.py`, `distill_cli.py` |

The deterministic stages run upstream with no fork work. The `ManualClassifier`
and `Distiller` seams stay abstaining upstream (no model shipped), so an unwired
deployment distills nothing rather than fabricating a rule; a fork wires
LLM-backed implementations and any siloed-source connector via the seam recipe in
[downstream-fork-seam-recipes.md § 5.16](../fork-and-sequencing/downstream-fork-seam-recipes.md#516-manual-distillation-manualsource--manualclassifier--distiller).

## Open decisions

- **Chunking + extraction prompt** for each manual format (PDF vs wiki vs Markdown)
  is fork-supplied config, versioned like any other prompt.
- **Coverage-diff heuristic** (what counts as an "imperative statement") needs
  tuning per manual style; start conservative and human-review the flags.
- **Manual-source cadence**: how often the watcher re-distills a changed manual
  revision reuses the source-watcher cadence model from
  [rule-catalog-collection.md](rule-catalog-collection.md); a manual revision bumps
  the content hash and re-enters the pipeline.
- **Parsing fidelity.** Rich source formats (tables, embedded diagrams and dashboard
  screenshots, Confluence macros, Notion toggles and embeds) lose information under
  naive text extraction, and a parsing loss is an extraction loss. Layout-aware
  parsing is the baseline; a diagram-only procedure may need a vision model, tracked
  as a per-format fork decision.
- **Data residency of extraction.** Step 2 sends confidential manual text to an LLM,
  which many enterprises forbid for external frontier models. The fork pins the
  extraction model to an in-tenant / no-training deployment (or a local model) so the
  manual never leaves the trust boundary; the choice is fork config, never hardcoded.

## Implementation status

Upstream ships the generic, customer-agnostic pieces of this design in code; the
LLM-backed extraction and the manuals themselves stay fork-owned.

| Piece | Status | Where |
|---|---|---|
| Distiller seam (contracts + Protocol + abstaining default) | shipped | [shared/providers/distiller.py](../../../src/fdai/shared/providers/distiller.py) |
| Coverage diff (deterministic false-negative guard) | shipped | [pipeline/distill/coverage.py](../../../src/fdai/rule_catalog/pipeline/distill/coverage.py) |
| `manual-distill` source parser id | shipped | [source_manifest.schema.json](../../../src/fdai/rule_catalog/schema/source_manifest.schema.json) |
| Container binding (`distiller`, default `AbstainingDistiller`) | shipped | [composition](../../../src/fdai/composition/) |
| LLM extraction (prose -> candidates) | fork | a fork registers a `Distiller` |
| Back-translation round-trip | backlog | - |

The upstream default `AbstainingDistiller` extracts nothing, so with no fork binding
the pipeline promotes nothing - the fail-safe. The coverage diff is a pure
deterministic function (section-heading + normative-term counting, fenced code
skipped) and runs without any model.

## Next steps

| To learn about | Read |
|---|---|
| Where rules come from and their YAML shape | [rule-catalog-collection.md](rule-catalog-collection.md) |
| Authoring, scoping, exemption, promotion | [rule-governance.md](rule-governance.md) |
| Runbook-as-code workflow schema | [rule-catalog/workflows](../../../rule-catalog/workflows/) |
| The continuous quality + T1 pipeline | [phase-2-quality-and-t1.md](../phases/phase-2-quality-and-t1.md) |
| Where customer manuals and rules live | [downstream-fork-guide.md](../fork-and-sequencing/downstream-fork-guide.md) |
