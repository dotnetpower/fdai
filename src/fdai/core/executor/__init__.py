"""Per-resource lock; idempotent apply via delivery adapters.

Public exports (P1 W-3 Step 3e):

- :class:`~fdai.core.executor.executor.ShadowExecutor` - the one
  execution surface for P1 remediation PRs; enforces all seven safeguards
  and closes every attempted publish with an audit outcome.
- :class:`~fdai.core.executor.executor.ExecutorConfig` /
  :class:`~fdai.core.executor.executor.ExecutorOutcome` /
  :class:`~fdai.core.executor.executor.ExecutionResult` - data types
  callers audit against.
- :class:`~fdai.core.executor.port.ThorExecutionPort` - injected composition
  boundary for the existing in-process execution surfaces.
- :class:`~fdai.core.executor.port.MutationDependencyReadiness` - immutable
  Saga durability and Vidar recovery-binding evidence for runtime composition.
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
from fdai.core.executor.port import (
    InProcessThorExecutionPort,
    MutationDependencyReadiness,
    ThorExecutionPort,
    ThorSafetyDependencyReadiness,
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
    "InProcessThorExecutionPort",
    "MutationDependencyReadiness",
    "RenderError",
    "RenderRequest",
    "ResourceLockManager",
    "ShadowExecutor",
    "TemplateRenderer",
    "ThorExecutionPort",
    "ThorSafetyDependencyReadiness",
    "ToolCallExecutionOutcome",
    "ToolCallExecutionResult",
    "ToolCallShadowExecutor",
    "is_strictly_stricter_than",
    "strictest_execution_path",
]
