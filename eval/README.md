# Evaluation assets

This directory owns repository evaluation data that exercises active FDAI behavior. It is separate
from the dormant external-harness contracts under `evaluation-sdk/` and the retained driver
packages under `benchmarks/`.

## Layout

| Path | Purpose |
|------|---------|
| `golden-dataset/` | 280 English/Korean cloud-operations question pairs with 35 semantic, runtime-context, ontology traversal, evidence, limitation, and authority expectations. |

Evaluation assets contain no customer observations, fixed operational answers, credentials, or
execution authority. A runner should resolve each question against the exact principal-scoped
ontology release and treat missing, stale, incomplete, or conflicting evidence as an explicit
limitation rather than a healthy result.

The golden dataset uses generic Azure resource-family and relationship shapes without retaining
subscription identifiers, resource names, resource groups, endpoints, or provider payloads. Its
runtime-context field distinguishes implemented incident binding and server scope from questions
that must first clarify an exact target.

## Testing

Run the focused static contract check from the repository root:

```bash
uv run pytest -q --no-cov tests/integration/evaluation/test_golden_dataset.py -o addopts=''
```