# Ontology retrieval diagnostics

Use these synthetic datasets to diagnose instance-candidate retrieval before considering runtime
activation. Neither a dataset, an offline replay, nor a passing diagnostic grants production
qualification or execution authority.

## Files

| File | Purpose |
|------|---------|
| [instance-corpus.v1.json](../../eval/ontology-retrieval/instance-corpus.v1.json) | Frozen 24-object fixture across four ObjectTypes. |
| [instance-calibration.v1.json](../../eval/ontology-retrieval/instance-calibration.v1.json) | Historical 24-query calibration; preserve its questions and labels. |
| [instance-calibration.v2.json](../../eval/ontology-retrieval/instance-calibration.v2.json) | Expanded 64-query calibration, including all v1 calibration cases unchanged. |
| [instance-holdout.v1.json](../../eval/ontology-retrieval/instance-holdout.v1.json) | Spent holdout. Preserve its evidence; don't tune on it or reuse it for qualification. |
| [instance-holdout.v2.json](../../eval/ontology-retrieval/instance-holdout.v2.json) | Spent holdout. Independently authored and reviewed; measured once at `2572f9a1b1`. Don't tune on its cases or reuse it for qualification. |
| [instance-calibration.v3.json](../../eval/ontology-retrieval/instance-calibration.v3.json) | 64 new diagnostic calibration cases for the holdout v2 failure classes. Calibration only; it can't qualify a change. |
| [instance-holdout.v3.json](../../eval/ontology-retrieval/instance-holdout.v3.json) | Spent holdout. A blinded author wrote it and a separately blinded reviewer reviewed it; measured once at `19bbbe3c95`. Don't tune on its cases or reuse it for qualification. |
| [instance-holdout.v4.json](../../eval/ontology-retrieval/instance-holdout.v4.json) | Frozen, unmeasured holdout for the next single qualifying run. A blinded author wrote it and a separately blinded reviewer reviewed it; neither read earlier holdout text, prompts, adapters, or this runbook. Don't read, tune on, or measure it outside that run. |

The v2 calibration has 32 singleton positives, eight multi-target positives and 24 no-match cases.
Each language covers four distinct singleton targets per type and at least four samples for every
measured cohort metric. Separate-context agent review checked all 64 labels against the corpus and
declarations. Two initially ambiguous fallback instructions were corrected before measurement.
This is label review only: synthetic coverage is not representative production evidence or human
approval. Both qualification-related metadata flags remain `false`.

## Run calibration without opening a holdout

Use `prepare_ontology_retrieval_campaign` and `execute_ontology_retrieval_campaign` with
`calibration_only=True` and `holdout_cases=()`. Supply v2 calibration cases, the real canonical
document build, secured gateway, isolated storage and the exact reviewed ResourceType terms.
Standalone calibration enforces every policy cohort and sample floor before embedding.

The input binding includes case order, labels, source documents and both policies. The expected
upper bound is 92 embedding requests: 28 documents and 64 questions. Existing execution ceilings
remain 128 requests, 600 seconds overall, 120 seconds preparation and five seconds per call.
Preparation and source/model checks are shared with the full campaign.

Inspect `report.campaign.calibration.passed` for the calibration outcome. A calibration-only
report has no holdout and its full-campaign `passed` remains `False`, even if calibration passed.
Use a newly frozen and independently reviewed disjoint holdout for later qualification.

## Retain and replay vectors privately

For a separately authorized live diagnostic, select
`OntologyEvaluationEvidence(new_private_path, source_commit=attested_sha, retain_vectors=True)`.
Vector retention is opt-in; the default writer doesn't retain vectors. The caller still owns
target attestation, consent, private storage and cleanup.

Each completed embedding records its exact UTF-8 input digest, model identity, dimension, call
index and validated vector. Input text isn't copied into these records. Vectors are still derived
data: keep the evidence private and outside Git. The writer uses exclusive mode-0600 creation and
flushes each result before another call. The existing 4 MiB record and 16 MiB file limits remain;
opt-in vector retention permits at most 262 records for the bounded 128-call attempt.

Load `OntologyEvaluationReplayEmbedder.from_evidence` with the expected whole-file SHA-256 digest
(`sha256:<hex>`), full source commit and `(space_id, model_version, dimension)` tuple. Supply this
adapter to the same executor with fresh isolated state and the unchanged source documents.
Replay accepts only complete private regular files with consistent intent/result pairs and model
identity. Missing vectors, different text bytes, corrupt records and mismatched pins fail without
a provider fallback. Re-recorded offline output cannot refresh the original capture provenance.

Reports distinguish `embedding_source="offline_replay"` from `caller_supplied` and retain
`replay_evidence_digest`. `embedding_calls` counts interface requests, not live provider calls
when replaying. `caller_supplied` alone doesn't attest that a real provider ran. File/model pins
establish consistency, not provider authenticity, representativeness or activation authority.

## Diagnose typed candidate membership

The optional `OntologyCandidateSelection` path evaluates already-proposed conditions through
current secured ObjectSet reads. It doesn't interpret natural-language words or invoke a model.
The caller remains responsible for the proposal's meaning; matching its conditions is not proof
that it understood the question.

Bind a proposal with `OntologyCandidateSelection.bind` and pass it to the prepared reader's
`search(selection=...)`. The binding covers the exact query, manifest and snapshot. Conditions
within a clause are combined with AND; clauses are unioned and duplicate identities are removed.
The reader snapshots nested operands before awaiting any read.

- Proposals are limited to 32 KiB, eight clauses, 16 conditions per clause and 100 explicit IDs
  per clause. Empty proposals and oversized inputs are rejected rather than truncated.
- The service owns the principal, purpose, cutoff, relationship exclusion and 1,000-row
  ObjectSet limit. Predicate-property access uses the gateway's existing permission check.
- Every scope must be complete, current and without hidden identities. Every matched object's
  canonical content must match the prepared source, including matches outside the display limit.
- The reader sorts matches by canonical document ID and reauthorizes the displayed objects.
  It retains the scope and final authorization receipt digests, including scope evidence for an
  empty result. A no-candidate outcome still doesn't prove graph absence.
- `score_kind="predicate_membership"` identifies constant membership values of `1.0`, not
  similarity scores or confidence. `selection_digest` binds strategy
  `secured-objectset-membership.v1` and the snapshotted proposal. The existing raw ranking path
  and exact-ID path retain their behavior and identify their respective score kinds.
- The exact-ID path treats an `object:<ObjectType>:<id>` document ID as a typed identity token.
  If the token is present in the query and no prepared document has that exact ID, the reader returns
  no candidates with `score_kind="exact_identity"` instead of falling through to semantic ranking.
  This is identity validation only; it does not infer meaning from aliases, labels or phrases.

`typed_selection_available` defaults to `False` and also requires semantic search availability.
An earlier embedding-ranking qualification cannot enable this new strategy. Runtime activation
remains disabled. The frozen raw-ranking reports don't qualify this path: model/prompt provenance,
actual semantic proposal evaluation and a newly reviewed holdout are still required.

## Propose meaning with the diagnostic model adapter

Explicitly resolve `diagnostic.ontology-candidate-selection` for `semantic.query.plan` from
`FileSystemPromptRegistry` and compile it with `PromptAssembler`. This is an observation-mode
profile (`shadow`), not a replacement for the active plan profile.

Configure a separate `AzureOpenAISemanticPlanningModel` with that compiled plan text and replay
manifest, exactly one target and a timeout no greater than 20 seconds. Pass the profile's
`reasoning_effort` and `reserved_output_tokens` to the adapter configuration; omitting the effort
silently runs the provider default instead of the reviewed profile. Call
`propose_candidate_selection` with the query, manifest, complete canonical build and staged
snapshot. The source validator checks the generation and principal manifest before dispatch.
Context above 128 KiB, changed content after input minimization, and prompt-budget overflow hold
the call; no document is silently omitted.

Candidate proposals use Azure OpenAI structured outputs. The request sends
`response_format.type="json_schema"` with a strict schema equivalent to or stricter than
`OntologyCandidateProposal`, and derives `object_type` and per-type predicate `property` enums from
the same principal manifest and allowed predicate-property catalog sent in the prompt payload. The
adapter upgrades the request API version to `2024-10-21` when the resolved target's default API
version predates structured outputs. The request-parameter digest includes the effective response
format, API version, timeout and output-token ceiling, so retained semantic evidence only replays
against the same structured contract.

The result retains an input digest and the adapter's model observation, including the transmitted
prompt/schema replay manifest. A selection carries typed clauses and one exact source quote per
clause. Quotes verify attribution, not semantic entailment. A clarification carries its explicit
reason and no selection. **Handle clarification before calling the reader:** passing `None` to
`search(selection=...)` would select the pre-existing raw retrieval path, not a clarification.

The diagnostic prompt instructs the model to use exact `object_ids` when the query identifies
specific instances already present in the supplied canonical documents. It reserves predicates for
genuine property-constrained sets, such as severity, criticality, type, status, or kind. This keeps
identity mediated by the model and verified by code; it doesn't add phrase tables or lexical lookup
logic.

The prompt also states the evaluator's exact predicate semantics. A predicate reads one top-level
property. `exists` and `absent` test only that property's presence. `contains` matches a substring
of text, an equal element of an array, or an equal key of an object, so a requested entry inside an
object-valued property, such as a Resource whose `properties` object has an `aliases` entry, is
expressed as `contains` with that key. `at_least` and `at_most` are inclusive and compare numbers
numerically and text in code-point order, so ISO 8601 UTC timestamps in the documents' form compare
chronologically. Wording about why the requester is asking is context, while any stated property of
the requested objects, including its `purpose`, remains a condition. Focused tests pin each stated
meaning to `object_matches_predicates` and show that declared predicates reproduce the nested-entry
and time-window calibration labels.

**Nested-value conditions.** ObjectSet predicates read top-level properties only, so a request
constrained by a value inside an object-valued property, such as Resource `properties.purpose`, was
inexpressible. The model returned a clarification, emitted a predicate that couldn't match, or
selected an instance it judged itself. A clause can now carry `nested_predicates`. Each one names a
top-level property, one key inside it, and the same operator and operand shapes as `ObjectPredicate`.

- **Evaluation:** the reader adds an `exists` predicate on each named parent, so the secured gateway
  authorizes the parent as it does any predicate property. It then applies the nested conditions to
  the ACL-projected materialized records with `object_matches_predicates`. Only instances whose
  parent holds an object can match, so `absent` means a missing key inside an existing parent.
- **Schema:** the payload lists `allowed_nested_predicate_keys`, the keys observed in the prepared
  projection for each allowed object-valued property. The strict schema has one nested variant per
  parent with nullable operands. A schema above 500 enum values holds before dispatch.
- **Bounds and digests:** a clause allows 16 predicates and 16 nested predicates. The shared
  ObjectSet contract is unchanged. A clause without nested conditions serializes as before, so its
  proposal digest is unchanged. The payload and response-schema digests do change, so verify
  earlier evidence with the source commit it records.

A qualifier that no property stores but the documents show directly, such as the language of a
stored alias, stays a condition. The model keeps the expressible conditions and adds exact
`object_ids` for only the satisfying instances, and returns an unsupported-constraint clarification
instead of a near match when none satisfies it. An earlier sentence that sent stored nested values
to exact `object_ids` caused near-match substitution and was reverted before nested conditions
existed.

Before a live semantic calibration, dry-run all planned calibration cases with the exact
manifest-bound response schema and prompt profile. The dry-run should report the maximum and median
estimated request tokens and fail before any provider call when any case exceeds the request-token
budget. For quote attribution, each clause carries one quote. The provider-facing schema keeps this
as free text so the structured-output grammar stays constant for the manifest; the exact-span
validator then drops invalidly attributed clauses before membership evaluation. If every clause is
dropped, the case records no candidates.
The diagnostic profile owns the model role and optional reasoning effort. The current reviewed
diagnostic candidate-selection role is `t2.reasoner.primary` with `reasoning_effort="low"` for
models that support the field; the effort is included in the request-parameter digest.

Semantic evaluation bounds each proposal call at 20 seconds and keeps the 600-second stage total;
embedding calibration keeps its five-second call bound. The earlier five-second ceiling came from
the embedding budget. Calibration evidence on the reviewed role shows provider-side tail latency
that output size doesn't explain: p50 about 2.2 seconds, p95 about 3.4-3.5 seconds, and calls
that reached the five-second ceiling about once every 24-36 calls. The qualifying attempt at
`84d7d1a26b` aborted on that deadline in both stages before any quality result. On 2026-10-08,
two calibration attempts on `gpt-5.6-sol` version `2026-07-09` aborted on the later 10-second
deadline after 23-24 calls at different cases, while completed calls showed p50 2.0-2.6 seconds and
a maximum of 8.2-8.3 seconds, so the bound rose to 20 seconds. This is a
diagnostic bound only. It doesn't approve production latency, and enabling semantic ranking
anywhere still requires a separate latency qualification.

The 2026-10-05 development semantic calibration at source `91d537c36b` plus uncommitted changes
completed 64 proposal calls in 151.7 seconds with evidence digest
`sha256:b0ece2df7a47f3ed280035822b9331fab3f9ca853fc2dca441b9eaab47c70ebb`.
Every v2 calibration cohort metric was `1.0`, `passed=True` and offline verification succeeded.
Per-call latency, including bookkeeping, was p50 2.23 seconds, p90 3.08 seconds, p95 3.38 seconds
and max 5.10 seconds. Treat the 5.10-second near-bound tail as residual risk for the final run.
This is development evidence only because it was not measured on a merged immutable commit.

This diagnostic method permits one attempt only. Provider failures, invalid JSON, incomplete
model choices, invalid quotes and deadline expiry never become successful empty searches. It
doesn't change ordinary frame/plan retry behavior. The caller still owns live authorization,
actual model/version attestation, durable per-call evidence, evaluation binding and total budgets.
Mocked adapter tests don't establish live quality or qualify runtime activation.

Earlier diagnostic history remains relevant: raw embedding ranking fails the v2 calibration, the
mini semantic model passed only 5 of 8 filtered failure cases, stronger-role attempts encountered
five-second tail timeouts, `reasoning_effort="minimal"` was rejected by the deployment/API path,
and the constant manifest-bound structured schema with `reasoning_effort="low"` passed the
development v2 calibration.

The qualifying diagnostic at merged `2572f9a1b1` ran calibration v2 and the independently reviewed
`instance-holdout.v2` once each, under a strict replay verification. Calibration passed every
cohort at `1.0`. The holdout failed: en-positive and ko-positive recall@5 and MRR were `0.938` (15
of 16 each), and ko-adversarial no-match precision was `0.5`. Every other cohort was `1.0`.
Per-call latency stayed within the 10-second bound, with a holdout maximum of 8.3 seconds.
Semantic ranking stays disabled. Both holdouts are spent. A later change needs failure-class
diagnosis from calibration, the corpus, and newly reviewed calibration samples only, followed by
a newly authored independent `instance-holdout.v3`. That holdout now exists and is unmeasured.

Development diagnostics on 2026-10-08 used the attested `gpt-5.6-sol` deployment, version
`2026-07-09`, with the reviewed `low` effort. Before nested conditions, calibration v2 passed and
calibration v3 failed with eight positive or ambiguous misses; the unchanged earlier prompt also
failed v3 with seven. An independent blinded reviewer reworded `cal-v3-en-p15`, whose strict
reading of "after the 08:30 update" excluded its labeled incident, and kept the labels. With nested
conditions and the document-visible qualifier statement at `828ff8909b`, calibration v2 and v3
both passed every cohort at `1.0` in two consecutive attempts each, with offline verification.
The qualifying diagnostic at merged `19bbbe3c95` ran calibration v2, calibration v3, and holdout
v3 once each with offline verification. Calibration v2 passed every cohort at `1.0`. Calibration
v3 missed two expressible positives as unsupported-constraint clarifications. Holdout v3 failed
only en-positive recall@5 and MRR at `0.9375` (15 of 16); every other cohort, including every
negative, adversarial, and ambiguous cohort, was `1.0`. Holdout v3 is spent, and its cases weren't
inspected.

The next cycle used calibration only. A statement that requesting a single instance or naming the
object's own role doesn't add a condition removed the spurious clarifications. A stricter variant
that required the model to name the inexpressible condition caused 20-second timeouts and was
replaced. A further statement copies free-text `contains` operands from a matching stored value
rather than the request's paraphrase. At `c3559f2c1f`, calibration v2 passed twice and calibration
v3 passed three times, every cohort at `1.0`, with no abort. A blinded author wrote the new
`instance-holdout.v4`, and a separately blinded reviewer corrected one case and approved it. It
stays unmeasured until one qualifying run at the merged commit.

## Measure semantic proposals separately

Use `prepare_ontology_semantic_evaluation` and `run_ontology_semantic_evaluation` with the
prepared typed reader and `OntologyEvaluationEvidence(..., semantic_proposals=True)`. Supply a
full source commit. This mode cannot retain embedding vectors or serve as legacy vector-replay
evidence. Preparation remains a separate bounded operation.

The plan binds ordered cases, unchanged labels and policies, canonical source, snapshot,
selection strategy, target, transmitted prompt/schema and effective request parameters,
including output tokens and timeout. Model name and version are caller-attested claims:
the caller still verifies the live deployment and obtains scoped authorization.

- **Limits:** at most 64 proposal-interface attempts, 600 seconds for measurement and 20
  seconds per question. Current-source validation runs before and after measurement, with a
  120-second ceiling per check inside the total deadline.
- **Durable ordering:** each call intent, accepted proposal and measurement is persisted before
  continuing. Proposal evidence retains typed conditions and source-quote spans, not whole
  quote strings. Keep this derived data private. Clarification is recorded explicitly and never
  falls through to raw retrieval.
- **Failure:** changed inputs, target/request binding drift, unavailable typed selection,
  provider failure, invalid output or persistence failure stop the attempt. Cancellation stays
  cancellation and retains prior measurements when the writer remains available.
- **Separate results:** semantic reports use their own binding and the existing cohort metric
  arithmetic and thresholds. A stage's `passed` does not qualify a complete campaign.
  `production_qualification` and `execution_authority` remain `False`.

### Interpret the final evidence outcome

Semantic evidence uses schema `1.1.0`, at most 198 records, and the existing private-file,
record-size and file-size controls. The elapsed measurement in a report is calculated before
terminal persistence; the runner checks its total deadline again after that write. If persistence
returns late, the runner raises and appends one `aborted` correction after `completed`, preserving
the measurements. **Use the final terminal outcome, not an earlier completed record.**
A correction cannot resume calls or upgrade an aborted outcome. Legacy evidence terminal rules
remain unchanged. If writing the failure itself fails, the attempt has no acknowledged terminal
outcome and cannot be treated as successful.

### Check retained semantic evidence offline

Use [verify_ontology_semantic_evidence](../../services/core-control-plane/src/fdai/delivery/catalog_search/ontology_semantic_evidence.py)
with an independently pinned file digest and the original prepared plan, build, manifest, staged
snapshot, cases, calibration queries, ranking policy, evaluation policy and required object types.
Do not obtain the expected plan or file digest from untrusted evidence and treat them as approval.

- **Consistency:** the verifier recomputes the frozen input binding, requires the exact complete
  record sequence, reconstructs proposals from their query spans, and compares per-call measurements
  with the final report. Returned IDs are unique, ordered, bounded and present in the prepared
  instance documents. Cohort metrics and failure codes are recalculated from the unchanged oracle.
- **Failure preservation:** a valid failed report is returned unchanged. Changed bindings, malformed
  records, missing calls and a trailing aborted correction raise a redacted `ValueError`.
- **Limits:** this check makes no provider call and neither reobserves the graph nor proves the
  authenticity of a model response, a result digest, or acknowledged terminal persistence.
  `production_qualification` and `execution_authority` remain `False`; runtime activation is unchanged.

Example: below-threshold recall remains `passed=False` after verification. Removing the failure
codes and rewriting the summary metrics does not turn the retained measurements into a pass.

## Testing

```bash
uv run pytest -q --no-cov \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_assets.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_campaign.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_execution.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_replay.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_evidence.py
```

These checks use deterministic vectors. They establish mechanics and data admission, not actual
embedding relevance.

For the typed membership boundary and its existing candidate/evaluation consumers:

```bash
uv run pytest -q --no-cov \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidate_selection.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_candidates.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_vector_deadlines.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_runner.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_execution.py
```

These tests supply typed conditions directly and make no live model request. They don't measure
natural-language understanding.

The model boundary, real diagnostic profile and existing planning behavior are covered by:

```bash
uv run pytest -q --no-cov \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_semantic_evidence.py \
  services/core-control-plane/tests/delivery/catalog_search/test_ontology_semantic_evaluation.py \
  services/core-control-plane/tests/delivery/azure/llm/test_ontology_candidate_proposal.py \
  services/core-control-plane/tests/delivery/azure/llm/test_semantic_planning.py \
  services/core-control-plane/tests/core/prompts/test_profiles.py
```

## Related docs

| To learn about | Read |
|---------------|------|
| Query contracts and diagnostic boundaries | [Ontology query coverage](../roadmap/interfaces/ontology-query-coverage-implementation-plan.md) |
| Current evidence and remaining gates | [Implementation ledger](../roadmap-implementation/interfaces/ontology-query-coverage-implementation-plan.md) |
