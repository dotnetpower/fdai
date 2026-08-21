# Cloud Operations Golden Dataset

This directory contains versioned English and Korean operator questions for regression testing the
FDAI semantic query path. The corpus checks whether a question resolves to the expected ontology
objects, follows declared relationship directions, uses verified evidence, and preserves read-only
authority. It does not prescribe a fixed natural-language answer or store environment-specific
facts.

> **Runtime status:** This dataset targets the active conversational semantic-query path. It does
> not reactivate the dormant `evaluation-sdk` host integration or the external benchmark drivers.

## Files

| File | Purpose |
|------|---------|
| `expectations.json` | Locale-neutral semantic, ontology traversal, evidence, and safety oracle. |
| `coverage.json` | Seven-perspective, runtime-context, and assurance-axis mapping for every logical expectation. |
| `questions.source.yaml` | Reviewed bilingual intent source for deterministic wording generation. |
| `questions.en.json` | Generated English operator wording keyed by case and expectation identity. |
| `questions.ko.json` | Generated Korean operator wording with the same case identities. |
| `expectations.schema.json` | Strict JSON Schema for the locale-neutral oracle. |
| `coverage.schema.json` | Strict JSON Schema for perspective and assurance coverage. |
| `questions.schema.json` | Strict JSON Schema for one localized question file. |
| `semantic-judgment-assurance.json` | Frozen #252 edge overlay, lexical baseline, structured-boundary replay, and acceptance thresholds. |
| `semantic-judgment-assurance.schema.json` | Strict schema for the #252 edge overlay and metric inputs. |

Do not hand-edit `questions.en.json` or `questions.ko.json`. Generate both from the reviewed source:

```bash
uv run python scripts/automation/build_golden_dataset.py
```

## Dataset shape

The corpus contains 35 logical expectations and eight wording variations per expectation, for 280
English/Korean semantic pairs and 560 localized questions. Each of the seven perspectives has five
expectations: `resource`, `service`, `operation`, `policy`, `business`, `causal`, and `action`.
The coverage matrix also includes all five evidence postures, all five terminal postures, all four
case classes, and all four anchor kinds. Action cases are always `draft_only`.

The questions use generic shapes from Azure network, compute, Application Gateway, Azure
Kubernetes Service (AKS), Pod, Container Apps, PostgreSQL, Storage, Key Vault, Event Hubs, and
observability resources. They include attachment, peering, private-link, containment, activity,
metric, and evidence-health scenarios without retaining any live resource identity or provider
payload.

The semantic-judgment overlay adds paraphrase, unseen synonym, negation and correction,
hypothetical and quoted language, prior-turn omission, multiple intents, mixed language,
adversarial keyword stuffing, and model-failure cases. Its metrics are synthetic contract-replay
evidence, not a live model-quality or operational-readiness claim. The focused test recomputes
legacy and treatment recall, precision, terminal-outcome accuracy, authority violations, and
lexical fallbacks from the frozen records.

Official product names and resource kinds are required semantic vocabulary, not customer data.
Use names such as `Application Gateway`, `AKS`, `Pod`, and `PostgreSQL Flexible Server` when they
determine the expected resource type or relationship path. A reviewed common abbreviation can
appear beside its official name, as in `Application Gateway` commonly called `AppGW`. Never replace
the official name with an unexplained abbreviation, and never add a live instance name, resource
group, resource id, endpoint, tenant, or subscription value.

## Runtime context

`anchor_kind` is the conceptual question-universe axis. It does not prove that the current
Operator-to-Core wire can deliver that context. Every coverage row and generated question
therefore carries one separate `runtime_context` value:

| Value | Evaluation behavior |
|------|---------------------|
| `incident_binding` | Use the incident identity and correlation already linked to the conversation. This is the only object binding currently implemented by the semantic-turn contract. |
| `server_scope` | Use only the principal's server-owned authorized scope. The question must not invent a narrower resource. |
| `explicit_target_required` | Expect clarification until the operator supplies an exact resource, service, change, decision case, recovery plan, or workload identity. |
| `none` | The wording contains enough catalog or declaration context and needs no runtime object binding. |

Generated wording must not say `selected` or `선택한`. Incident cases say that the incident is
linked to the current conversation. Other object-specific questions name a generic resource family
and expect target clarification instead of implying hidden UI state.

## Evaluation contract

Join each localized question's `expectation_id` and `runtime_context` to the matching
`semantic_pair_id` in `expectations.json` and its coverage row. A regression runner should then
submit the question through the real semantic-turn boundary and verify all of the following:

1. The turn uses `verified_query_plan`, or returns one of the case's allowed typed non-answer
   dispositions when required evidence is unavailable.
2. Semantic retrieval resolves every required ObjectType, LinkType, and FunctionType against the
   exact principal-scoped ontology release.
3. Every executed relationship path follows the declared stored direction or its explicitly
   requested inverse and stays within the expected depth bounds.
4. The answer cites query evidence, distinguishes missing or stale evidence from a verified empty
   result, and includes the required limitations.
5. An `explicit_target_required` case returns clarification before operational reads when the
   request supplies no exact target.
6. The result reports `execution_authority=false` and makes none of the forbidden claims.

The expected facts are fact kinds, not literal values. For example, a case can require
`resource.status` without claiming that the selected resource is healthy. This keeps the corpus
valid across environments and prevents a stale fixture from becoming operational truth.

## Adding a question

Add one locale-neutral case to `expectations.json`, one matching coverage row, and one bilingual
request to `questions.source.yaml`. The generator creates all eight wording variations. Keep
resource identities and customer data outside the repository. Add a new relationship expectation
only when its ObjectType and LinkType declarations already exist in the shipped catalog.

## Validation

Run the focused dataset contract test from the repository root:

```bash
uv run pytest -q --no-cov tests/integration/evaluation/test_golden_dataset.py -o addopts=''
```

The test validates all schemas, generated-artifact drift, 280-case bilingual parity, perspective,
runtime-context, and assurance-axis coverage, sanitized resource-scenario diversity, wording
diversity, stable ordering, catalog object and link references, relationship direction and depth,
exact-release retrieval requirements, and the read-only authority ceiling.
