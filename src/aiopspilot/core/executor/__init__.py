"""Per-resource lock; idempotent apply via delivery adapters.

Public exports (P1 W-3 Step 3e):

- :class:`~aiopspilot.core.executor.executor.ShadowExecutor` - the one
  execution surface for P1 remediation PRs; enforces the four safety
  invariants and always writes an audit entry.
- :class:`~aiopspilot.core.executor.executor.ExecutorConfig` /
  :class:`~aiopspilot.core.executor.executor.ExecutorOutcome` /
  :class:`~aiopspilot.core.executor.executor.ExecutionResult` - data types
  callers audit against.
- :class:`~aiopspilot.core.executor.lock.ResourceLockManager` - per-resource
  serialization.
- :class:`~aiopspilot.core.executor.renderer.TemplateRenderer` /
  :class:`~aiopspilot.core.executor.renderer.RenderRequest` /
  :class:`~aiopspilot.core.executor.renderer.RenderError` - remediation
  template substitution.
"""

from aiopspilot.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
)
from aiopspilot.core.executor.executor import (
    ExecutionResult,
    ExecutorConfig,
    ExecutorOutcome,
    ShadowExecutor,
)
from aiopspilot.core.executor.lock import ResourceLockManager
from aiopspilot.core.executor.renderer import (
    RenderError,
    RenderRequest,
    TemplateRenderer,
)

__all__ = [
    "DirectApiExecutionOutcome",
    "DirectApiExecutionResult",
    "DirectApiShadowExecutor",
    "ExecutionResult",
    "ExecutorConfig",
    "ExecutorOutcome",
    "RenderError",
    "RenderRequest",
    "ResourceLockManager",
    "ShadowExecutor",
    "TemplateRenderer",
]
