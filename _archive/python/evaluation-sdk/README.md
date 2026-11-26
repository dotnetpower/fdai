# FDAI evaluation SDK

This retained standalone package defines benchmark-neutral contracts for external evaluation
drivers. It contains no FDAI control-plane, agent, delivery, runtime, composition, benchmark,
oracle, dataset, or grader implementation.

> **Runtime status:** Dormant. The current Core distribution has no `EvaluationHost`, evaluation
> runtime entry point, or legacy `fdai.benchmarking` facade. The root FDAI `dev` extra does not
> install this package or its benchmark drivers. The package remains a workspace member so CI can
> preserve its contracts, focused tests, type checks, and independently buildable wheel until a
> reviewed host reactivation is approved.

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

The retained runner contract expects an external driver to receive an `EvaluationHost` from its
launcher. The current FDAI runtime does not provide that host.

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

## Reactivation boundary

Reactivation requires a service-owned public host, focused host integration tests, an explicit
composition and runtime entry point, and governed end-to-end evidence. Restoring only a package
dependency or the deleted compatibility facade is insufficient. The active conversational
regression corpus lives under `eval/golden-dataset/` and does not depend on this SDK.

## Testing

Run the SDK checks from the repository root:

```bash
PYTHONPATH=evaluation-sdk/src .venv/bin/python -m pytest -q evaluation-sdk/tests \
  --cov=fdai_evaluation_sdk --cov-branch --cov-fail-under=90 -o addopts=''
.venv/bin/mypy --strict evaluation-sdk/src/fdai_evaluation_sdk
.venv/bin/ruff check evaluation-sdk/src evaluation-sdk/tests
```
