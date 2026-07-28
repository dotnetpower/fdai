# FDAI evaluation SDK

This standalone package defines benchmark-neutral contracts for external evaluation drivers. It
contains no FDAI control-plane, agent, delivery, runtime, composition, benchmark, oracle, dataset,
or grader implementation.

## Public API

| Surface | Purpose |
|---------|---------|
| `EvaluationHost` / `EvaluationSession` | Open a bounded session, execute neutral tasks, exchange artifacts, and close resources. |
| `EvaluationRequest` | Declare identity, purpose, capability and authority ceilings, limits, deadlines, and policies. |
| `EvaluationTask` / `EvaluationResult` | Exchange correlated work and terminal FDAI receipts without benchmark scoring. |
| `ArtifactSpec` / `ArtifactRef` | Declare bounded outputs and reference immutable content-addressed artifacts. |
| `EvaluationWorkspace` | Use task-scoped file, patch, build, and test operations without host paths or raw shell commands. |
| `EvaluationAdapter` / `EvaluationRunner` | Translate one harness lifecycle and drive it through the public host. |

All serialized models are strict, frozen Pydantic contracts. Unknown fields, coercion, naive
timestamps, control characters, duplicate identities, cross-session artifact inputs, and values
outside declared bounds fail validation.

## Driver lifecycle

An external driver receives an `EvaluationHost` from its launcher. It does not discover or build
FDAI runtime internals.

```python
from fdai_evaluation_sdk import EvaluationRunner

summary = await EvaluationRunner(adapter=driver, host=host).run()
```

The runner verifies the exact SDK/host API version, opens one session, rejects duplicate and
cross-session task identities, submits only correlated results, and closes the session and adapter
after success, failure, timeout, or cancellation.

## Security boundaries

- Requested capabilities and authority are ceilings. The FDAI host can only reduce them.
- Workspace and substrate mutations are separate side-effect classes.
- Binary bytes move through bounded artifact streams, not metadata or logs.
- External validation receipts remain untrusted for FDAI execution.
- Benchmark packages, protocols, hidden tests, oracles, and graders stay outside this package.

## Migration

Existing `fdai.benchmarking` callers can remain on the legacy facade through the FDAI `0.1.x`
release line while moving to this SDK. The compatibility surface is eligible for removal only in
FDAI `0.2.0` or later after one documented minor release window.

## Testing

Run the SDK checks from the repository root:

```bash
PYTHONPATH=evaluation-sdk/src .venv/bin/python -m pytest -q evaluation-sdk/tests \
  --cov=fdai_evaluation_sdk --cov-branch --cov-fail-under=90 -o addopts=''
.venv/bin/mypy --strict evaluation-sdk/src/fdai_evaluation_sdk
.venv/bin/ruff check evaluation-sdk/src evaluation-sdk/tests
```
