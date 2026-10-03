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

`typed_selection_available` defaults to `False` and also requires semantic search availability.
An earlier embedding-ranking qualification cannot enable this new strategy. Runtime activation
remains disabled. The frozen raw-ranking reports don't qualify this path: model/prompt provenance,
actual semantic proposal evaluation and a newly reviewed holdout are still required.

## Propose meaning with the diagnostic model adapter

Explicitly resolve `diagnostic.ontology-candidate-selection` for `semantic.query.plan` from
`FileSystemPromptRegistry` and compile it with `PromptAssembler`. This is an observation-mode
profile (`shadow`), not a replacement for the active plan profile.

Configure a separate `AzureOpenAISemanticPlanningModel` with that compiled plan text and replay
manifest, exactly one target and a timeout no greater than five seconds. Call
`propose_candidate_selection` with the query, manifest, complete canonical build and staged
snapshot. The source validator checks the generation and principal manifest before dispatch.
Context above 128 KiB, changed content after input minimization, and prompt-budget overflow hold
the call; no document is silently omitted.

The result retains an input digest and the adapter's model observation, including the transmitted
prompt/schema replay manifest. A selection carries typed clauses and one exact source quote per
clause. Quotes verify attribution, not semantic entailment. A clarification carries its explicit
reason and no selection. **Handle clarification before calling the reader:** passing `None` to
`search(selection=...)` would select the pre-existing raw retrieval path, not a clarification.

This diagnostic method permits one attempt only. Provider failures, invalid JSON, incomplete
model choices, invalid quotes and deadline expiry never become successful empty searches. It
doesn't change ordinary frame/plan retry behavior. The caller still owns live authorization,
actual model/version attestation, durable per-call evidence, evaluation binding and total budgets.
Mocked adapter tests don't establish live quality or qualify runtime activation.

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
  services/core-control-plane/tests/delivery/azure/llm/test_ontology_candidate_proposal.py \
  services/core-control-plane/tests/delivery/azure/llm/test_semantic_planning.py \
  services/core-control-plane/tests/core/prompts/test_profiles.py
```

## Related docs

| To learn about | Read |
|---------------|------|
| Query contracts and diagnostic boundaries | [Ontology query coverage](../roadmap/interfaces/ontology-query-coverage-implementation-plan.md) |
| Current evidence and remaining gates | [Implementation ledger](../roadmap-implementation/interfaces/ontology-query-coverage-implementation-plan.md) |
