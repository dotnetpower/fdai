"""Executor path selection - R7 strictest-path combinator.

Implements the "strictest wins" rule from the
"Executor selection at dispatch" section of
``docs/roadmap/execution-model.md``:

- Each axis (ActionType default, RiskGate ``forced_execution_path`` on
  the resolved ceiling, a fork-installed overlay) proposes an
  :class:`ExecutionPath`.
- The executor picks the **strictest** proposal - i.e. the one that
  requires the most human review - never the fastest.

Strict order (by review-stringency, NOT by speed):

.. code-block:: text

    pr_manual   > pr_native   > direct_api
    (mandatory   (policy       (no diff)
     human       auto-merge)
     merge)

A fork MAY force every dispatch in prod to ``pr_manual`` via an env
axis; upstream MUST NEVER lift ``pr_manual`` to ``direct_api`` for
latency. That invariant is what
:func:`strictest_execution_path` encodes.

The function is deliberately small + pure so:

- The RiskGate can compose it at ceiling-resolution time.
- The executor can re-compose it at dispatch time (defense in depth
  against a stale ceiling).
- Property tests treat it as a total function over
  ``ExecutionPath | None``.
"""

from __future__ import annotations

from typing import Final

from aiopspilot.shared.contracts.models import ExecutionPath

# Higher value = stricter. Keep this table PRIVATE so a callers cannot
# depend on the numeric encoding - only on the function output.
_STRICTNESS: Final[dict[ExecutionPath, int]] = {
    ExecutionPath.DIRECT_API: 0,
    ExecutionPath.PR_NATIVE: 1,
    ExecutionPath.PR_MANUAL: 2,
}


class ExecutionPathSelectionError(ValueError):
    """Raised when the caller provided no path at all.

    Every dispatch has at least the ActionType's declared
    ``execution_path`` (a required field on the ontology), so a caller
    that ends up with (None, None) is a programmer bug we want to
    fail closed on rather than silently default.
    """


def strictest_execution_path(
    a: ExecutionPath | None,
    b: ExecutionPath | None,
) -> ExecutionPath:
    """Return the strictest of ``a`` and ``b``.

    ``None`` acts as "no opinion" - the other value wins. The function
    is commutative and associative over :class:`ExecutionPath` so
    a caller can fold over an arbitrary number of axis outputs by
    reducing pair-by-pair.

    Raises :class:`ExecutionPathSelectionError` when both inputs are
    ``None`` - see the class docstring for the fail-closed rationale.
    """
    if a is None and b is None:
        raise ExecutionPathSelectionError(
            "strictest_execution_path requires at least one non-None path"
        )
    if a is None:
        # b is guaranteed non-None by the guard above.
        return _guard_known(b)  # type: ignore[arg-type]
    if b is None:
        return _guard_known(a)
    a_rank = _STRICTNESS[_guard_known(a)]
    b_rank = _STRICTNESS[_guard_known(b)]
    return a if a_rank >= b_rank else b


def is_strictly_stricter_than(
    proposed: ExecutionPath,
    baseline: ExecutionPath,
) -> bool:
    """True iff ``proposed`` sits ABOVE ``baseline`` on the strictness
    ladder (more human review required).

    Used by the RiskGate to assert that an axis output can only
    ``raise`` the path, never lower it - see the R7 promotion
    invariant in the roadmap.
    """
    return _STRICTNESS[_guard_known(proposed)] > _STRICTNESS[_guard_known(baseline)]


def _guard_known(path: ExecutionPath) -> ExecutionPath:
    """Defense-in-depth: refuse an unknown enum value.

    ``ExecutionPath`` is a closed :class:`~enum.StrEnum`, so this
    branch is unreachable via the type system. It exists so a caller
    who forces the type via ``ExecutionPath("bogus")`` sees a clear
    error rather than a silent KeyError deep in ``_STRICTNESS``.
    """
    if path not in _STRICTNESS:  # pragma: no cover - StrEnum makes this unreachable
        raise ExecutionPathSelectionError(
            f"unknown ExecutionPath {path!r}; add to _STRICTNESS mapping"
        )
    return path


__all__ = [
    "ExecutionPathSelectionError",
    "is_strictly_stricter_than",
    "strictest_execution_path",
]
