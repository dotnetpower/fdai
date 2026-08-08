"""Executor path selection - R7 strictest-path combinator.

Implements the "strictest wins" rule from the
"Executor selection at dispatch" section of
``docs/roadmap/decisioning/execution-model.md``:

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

from fdai.shared.contracts.models import ExecutionPath

# Higher value = stricter. Keep this table PRIVATE so a callers cannot
# depend on the numeric encoding - only on the function output.
#
# NOTE: ``tool_call`` is intentionally ABSENT. It is off the
# substrate-mutation ladder (execution-model.md 5.6) - it mutates no
# substrate, so it is never ranked against pr/direct paths. It is
# dispatched purely by ``execution_path``; the functions below handle it
# explicitly rather than assigning it a bogus rank.
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
    # tool_call is off the substrate-mutation ladder (execution-model.md
    # 5.6). A same-value pair (or tool_call + None) collapses to
    # tool_call; mixing it with a substrate path means one action was
    # assigned two incompatible delivery surfaces - a programmer bug we
    # fail closed on rather than silently rank.
    if ExecutionPath.TOOL_CALL in (a, b):
        present = tuple(p for p in (a, b) if p is not None)
        if all(p is ExecutionPath.TOOL_CALL for p in present):
            return ExecutionPath.TOOL_CALL
        raise ExecutionPathSelectionError(
            "tool_call is off the pr_manual>pr_native>direct_api ladder "
            "(execution-model.md 5.6); it cannot be combined with a "
            "substrate execution path"
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
    """Defense-in-depth: refuse an off-ladder or unknown enum value.

    ``tool_call`` is a valid :class:`ExecutionPath` but sits OFF the
    substrate-mutation strictness ladder (execution-model.md 5.6), so it
    must never be ranked here - it is dispatched by ``execution_path``
    alone. Reaching this guard with ``tool_call`` means a caller tried to
    compare it against a pr/direct path, which is a programmer bug.

    ``ExecutionPath`` is otherwise a closed :class:`~enum.StrEnum`, so
    the final branch is unreachable via the type system. It exists so a
    caller who forces the type via ``ExecutionPath("bogus")`` sees a
    clear error rather than a silent KeyError deep in ``_STRICTNESS``.
    """
    if path is ExecutionPath.TOOL_CALL:
        raise ExecutionPathSelectionError(
            "tool_call is off the substrate-mutation strictness ladder "
            "(execution-model.md 5.6); it is dispatched by execution_path, "
            "never ranked against pr_native/direct_api/pr_manual"
        )
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
