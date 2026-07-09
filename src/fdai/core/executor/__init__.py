"""Per-resource lock; idempotent apply via delivery adapters.

Public exports (P1 W-3 Step 3e):

- :class:`~fdai.core.executor.executor.ShadowExecutor` - the one
  execution surface for P1 remediation PRs; enforces the four safety
  invariants and always writes an audit entry.
- :class:`~fdai.core.executor.executor.ExecutorConfig` /
  :class:`~fdai.core.executor.executor.ExecutorOutcome` /
  :class:`~fdai.core.executor.executor.ExecutionResult` - data types
  callers audit against.
- :class:`~fdai.core.executor.lock.ResourceLockManager` - per-resource
  serialization.
- :class:`~fdai.core.executor.renderer.TemplateRenderer` /
  :class:`~fdai.core.executor.renderer.RenderRequest` /
  :class:`~fdai.core.executor.renderer.RenderError` - remediation
  template substitution.
"""

from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
    DirectApiShadowExecutor,
)
from fdai.core.executor.executor import (
    ExecutionResult,
    ExecutorConfig,
    ExecutorOutcome,
    ShadowExecutor,
)
from fdai.core.executor.lock import ResourceLockManager
from fdai.core.executor.path_selection import (
    ExecutionPathSelectionError,
    is_strictly_stricter_than,
    strictest_execution_path,
)
from fdai.core.executor.renderer import (
    RenderError,
    RenderRequest,
    TemplateRenderer,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
    ToolCallShadowExecutor,
)

__all__ = [
    "DirectApiExecutionOutcome",
    "DirectApiExecutionResult",
    "DirectApiShadowExecutor",
    "ExecutionPathSelectionError",
    "ExecutionResult",
    "ExecutorConfig",
    "ExecutorOutcome",
    "RenderError",
    "RenderRequest",
    "ResourceLockManager",
    "ShadowExecutor",
    "TemplateRenderer",
    "ToolCallExecutionOutcome",
    "ToolCallExecutionResult",
    "ToolCallShadowExecutor",
    "is_strictly_stricter_than",
    "strictest_execution_path",
]
