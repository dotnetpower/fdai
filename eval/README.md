# Evaluation assets

This directory owns repository evaluation data that exercises active FDAI behavior. It is separate
from the dormant external-harness contracts under `evaluation-sdk/` and the retained driver
packages under `benchmarks/`.

## Layout

| Path | Purpose |
|------|---------|
| `golden-dataset/` | 280 English/Korean cloud-operations question pairs with 35 semantic, runtime-context, ontology traversal, evidence, limitation, and authority expectations. |
| `ontology-reasoning/` | 60 English/Korean reasoning cases with gold closed question forms and reviewed outcomes on a generic fixture graph, for the [ontology reasoning compiler](../docs/roadmap/interfaces/ontology-reasoning-compiler.md). |
| `ontology-retrieval/` | 24 synthetic instances across four current ObjectType schemas, 24 calibration questions, and 64 separately authored English/Korean holdout questions. Offline admission checks sample floors and frozen inputs; no live quality or production qualification is claimed. |

Evaluation assets contain no customer observations, fixed operational answers, credentials, or
execution authority. A runner should resolve each question against the exact principal-scoped
ontology release and treat missing, stale, incomplete, or conflicting evidence as an explicit
limitation rather than a healthy result.

The golden dataset uses generic Azure resource-family and relationship shapes without retaining
subscription identifiers, resource names, resource groups, endpoints, or provider payloads. Its
runtime-context field distinguishes implemented incident binding and server scope from questions
that must first clarify an exact target.

The instance-retrieval diagnostic includes nearby service/workload distractors and Incident
status/severity contrasts. Each language has positive, negative, ambiguous and adversarial cohorts;
the held-out set requires four samples for each measured metric and four distinct positive targets
per ObjectType. The candidate ranking policy is an unqualified hypothesis, not the runtime policy.
Its 116-call plan includes 28 document embeddings, 24 calibration queries and 64 held-out queries,
below the proposed 128-call ceiling. These assets grant no live-call permission. Independent review,
representativeness against the intended operating scope, observed model binding and fresh bounded
authorization remain prerequisites; a failed calibration must not open the holdout run.

The [campaign runner](../services/core-control-plane/src/fdai/delivery/catalog_search/ontology_evaluation_campaign.py)
now enforces this order against a prepared candidate reader. Admission freezes both ordered
datasets, calibration labels, model/document generation and policies before the first query.
Calibration uses the same metric thresholds but cannot satisfy the holdout's cohort or sample
floors. A failed calibration returns no holdout report. Provider errors, source/policy drift and
timeouts stop the attempt without retries and preserve completed diagnostic evidence.

Both query stages share one monotonic total deadline, with per-query deadlines capped at five
seconds. Document preparation and embedding happen before this runner and need their own bounded
authorization; a live driver still needs an enclosing budget covering all 116 planned calls and
preparation time. Stage-labelled reports remain diagnostic and cannot enable runtime search.

## Testing

Run the focused static contract check from the repository root:

```bash
uv run pytest -q --no-cov tests/integration/evaluation/test_golden_dataset.py -o addopts=''
```

Check every reasoning gold form against its reviewed outcome and execute each compiled, output-bearing form on the fixture graph:

```bash
uv run pytest -q --no-cov services/core-control-plane/tests/conversation/test_semantic_reasoning_cohort.py
```

Validate the instance-retrieval data against current declarations and the offline admission gate,
without any model or provider calls:

```bash
uv run pytest -q --no-cov services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_assets.py
```

Verify calibration sequencing and stop conditions through the actual reader with deterministic
test-only vectors:

```bash
uv run pytest -q --no-cov services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_campaign.py services/core-control-plane/tests/delivery/catalog_search/test_ontology_evaluation_runner.py
```
