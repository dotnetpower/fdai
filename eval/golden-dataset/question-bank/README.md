# FDAI Question Bank

This directory materializes FDAI's existing question surfaces into one bilingual review catalog.
It preserves each source's authority while giving maintainers stable question identities, six
operator-facing domains, independent readiness axes, and one deterministic drift check.

> The question bank is an inventory and authoring surface. Inclusion does not mean that a question
> has a complete semantic contract, runtime provider, current evidence, or live validation.

## Files

| File | Purpose |
|------|---------|
| [`question-bank.source.yaml`](./question-bank.source.yaml) | Source registry, domain mappings, Console mappings, defaults, and 50 operator candidates. |
| [`question-bank.source.schema.json`](./question-bank.source.schema.json) | Strict schema for the authoring source. |
| [`operator-question-expansion.source.yaml`](./operator-question-expansion.source.yaml) | Two hundred additional bilingual operator candidates grouped by the 12 supplied operational categories. |
| [`question-expansion.source.schema.json`](./question-expansion.source.schema.json) | Strict schema for an external candidate source. |
| [`question-bank.json`](./question-bank.json) | Generated machine-readable inventory of Golden, manual, Console, and candidate questions. |
| [`question-bank.schema.json`](./question-bank.schema.json) | Strict schema for the generated inventory. |
| [`review-catalog.md`](./review-catalog.md) | Generated bilingual view for human review. |

The materialized inventory contains 352 logical questions:

- 35 reviewed Golden expectations;
- 60 bilingual pairs formed from Q001-Q120;
- 7 Console starter questions;
- 250 operator candidates across seven domains, including Cost and FinOps.

## Source ownership

The registry is federated rather than duplicating existing source text:

| Source | Authority |
|--------|-----------|
| [`questions.source.yaml`](../questions.source.yaml) | Reviewed Golden intent wording. |
| [`expectations.json`](../expectations.json) | Semantic, ontology, evidence, and safety oracle. |
| [`coverage.json`](../coverage.json) | Perspective, context, and expected-posture coverage. |
| [`browser-session-test-prompts-q001-q120.md`](../../../docs/internals/browser-session-test-prompts-q001-q120.md) | Manual browser-session prompts and variants. |
| [`messages.en.json`](../../../console/src/i18n/messages.en.json) and [`messages.ko.json`](../../../console/src/i18n/messages.ko.json) | Console starter wording. |
| [`question-bank.source.yaml`](./question-bank.source.yaml) | Cross-source mappings, baseline operator candidates, and external candidate-source registration. |
| [`operator-question-expansion.source.yaml`](./operator-question-expansion.source.yaml) | The 200-question operational expansion. |

This boundary avoids a second editable copy of reviewed questions. The generated inventory records
the SHA-256 digest of every input so changes on any source surface require regeneration.
When supplied examples intentionally repeat the same wording in different categories, retain both
stable ids and set `duplicate_of` on the later entry. The compiler accepts duplicate canonical
wording only when every repeated entry points to one unambiguous canonical id.

## Readiness model

Readiness is represented by independent axes instead of one overloaded lifecycle value:

| Axis | Values |
|------|--------|
| Content review | `candidate`, `source_controlled`, `reviewed` |
| Semantic contract | `unassessed`, `partial`, `covered` |
| Runtime binding | `unassessed`, `unavailable`, `clarify`, `bound`, `mixed` |
| Evidence source | `unassessed`, `contract_only`, `retained`, `live` |
| Validation | `not_run`, `contract_passed`, `live_passed` |

For example, a readable and reviewed question can still have an unavailable runtime binding.
Likewise, passing schema checks does not become a live operational-readiness claim.

## Add or revise a question

Use the source that owns the question:

1. Add a small candidate set to the matching domain in `question-bank.source.yaml`. Add a large,
   independently reviewable set as a schema-valid external source and register it in
   `candidate_sources`.
2. Change existing Golden wording in `questions.source.yaml`, then regenerate the Golden artifacts.
3. Change Q001-Q120 in the manual prompt document.
4. Change Console starters in the English catalog first and keep the Korean overlay aligned.
5. Regenerate the question bank and review the domain, context, readiness, and safety columns.

Candidate action wording remains advisory or draft-only and always carries
`execution_authority: false`. A candidate becomes Golden only after it has a reviewed semantic
expectation, coverage row, evidence limitations, and forbidden-claim oracle.

## Generate and validate

Generate both artifacts from the repository root:

```bash
uv run python scripts/automation/build_question_bank.py
```

Run the focused question-bank and existing Golden checks:

```bash
uv run pytest -q --no-cov \
  tests/integration/evaluation/test_question_bank.py \
  tests/integration/evaluation/test_golden_dataset.py \
  -o addopts=''
```

The focused checks validate schemas, generated-artifact drift, stable source counts, all legacy
Q001-Q120 identities, Golden variations, bilingual candidate coverage, and the no-execution
authority boundary.
