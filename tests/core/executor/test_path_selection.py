"""Executor path selection - R7 strictest-path invariants.

Every rule from the roadmap (execution-model.md 5.4) is asserted:

- ``pr_manual`` is strictly stricter than ``pr_native`` is strictly
  stricter than ``direct_api``.
- ``strictest`` is commutative + associative over the three values.
- ``None`` acts as "no opinion" and is dominated by any real path.
- ``strictest(None, None)`` fails closed with
  :class:`ExecutionPathSelectionError`.
- ``strictest(a, b)`` NEVER returns a path that is less strict than
  the maximum-strict input (the R7 axis-can-only-raise invariant).
- ``is_strictly_stricter_than`` is strict (self-comparison is False).
"""

from __future__ import annotations

from itertools import product

import pytest

from fdai.core.executor import (
    ExecutionPathSelectionError,
    is_strictly_stricter_than,
    strictest_execution_path,
)
from fdai.shared.contracts.models import ExecutionPath

_PATHS: tuple[ExecutionPath, ...] = (
    ExecutionPath.DIRECT_API,
    ExecutionPath.PR_NATIVE,
    ExecutionPath.PR_MANUAL,
)


# ---------------------------------------------------------------------------
# Total ordering + strictness ladder
# ---------------------------------------------------------------------------


class TestStrictnessLadder:
    def test_pr_manual_is_strictly_stricter_than_pr_native(self) -> None:
        assert is_strictly_stricter_than(ExecutionPath.PR_MANUAL, ExecutionPath.PR_NATIVE)

    def test_pr_native_is_strictly_stricter_than_direct_api(self) -> None:
        assert is_strictly_stricter_than(ExecutionPath.PR_NATIVE, ExecutionPath.DIRECT_API)

    def test_pr_manual_is_strictly_stricter_than_direct_api(self) -> None:
        assert is_strictly_stricter_than(ExecutionPath.PR_MANUAL, ExecutionPath.DIRECT_API)

    def test_self_comparison_is_not_stricter(self) -> None:
        for path in _PATHS:
            assert is_strictly_stricter_than(path, path) is False

    def test_reverse_direction_is_not_stricter(self) -> None:
        assert is_strictly_stricter_than(ExecutionPath.DIRECT_API, ExecutionPath.PR_MANUAL) is False
        assert is_strictly_stricter_than(ExecutionPath.PR_NATIVE, ExecutionPath.PR_MANUAL) is False
        assert is_strictly_stricter_than(ExecutionPath.DIRECT_API, ExecutionPath.PR_NATIVE) is False


# ---------------------------------------------------------------------------
# Explicit 3x3 matrix
# ---------------------------------------------------------------------------


class TestStrictestMatrix:
    @pytest.mark.parametrize("path", _PATHS)
    def test_self_is_identity(self, path: ExecutionPath) -> None:
        assert strictest_execution_path(path, path) is path

    def test_direct_api_vs_pr_native(self) -> None:
        assert (
            strictest_execution_path(ExecutionPath.DIRECT_API, ExecutionPath.PR_NATIVE)
            is ExecutionPath.PR_NATIVE
        )

    def test_pr_native_vs_pr_manual(self) -> None:
        assert (
            strictest_execution_path(ExecutionPath.PR_NATIVE, ExecutionPath.PR_MANUAL)
            is ExecutionPath.PR_MANUAL
        )

    def test_direct_api_vs_pr_manual(self) -> None:
        assert (
            strictest_execution_path(ExecutionPath.DIRECT_API, ExecutionPath.PR_MANUAL)
            is ExecutionPath.PR_MANUAL
        )

    def test_pr_manual_always_wins(self) -> None:
        # No pairing lifts PR_MANUAL down the ladder.
        for other in _PATHS:
            assert (
                strictest_execution_path(ExecutionPath.PR_MANUAL, other) is ExecutionPath.PR_MANUAL
            )
            assert (
                strictest_execution_path(other, ExecutionPath.PR_MANUAL) is ExecutionPath.PR_MANUAL
            )


# ---------------------------------------------------------------------------
# None-handling
# ---------------------------------------------------------------------------


class TestNoneHandling:
    @pytest.mark.parametrize("path", _PATHS)
    def test_none_dominated_by_any_real_path(self, path: ExecutionPath) -> None:
        assert strictest_execution_path(path, None) is path
        assert strictest_execution_path(None, path) is path

    def test_both_none_raises(self) -> None:
        with pytest.raises(ExecutionPathSelectionError):
            strictest_execution_path(None, None)


# ---------------------------------------------------------------------------
# tool_call is off the substrate-mutation ladder (execution-model.md 5.6)
# ---------------------------------------------------------------------------


class TestToolCallOffLadder:
    def test_self_collapses_to_tool_call(self) -> None:
        assert (
            strictest_execution_path(ExecutionPath.TOOL_CALL, ExecutionPath.TOOL_CALL)
            is ExecutionPath.TOOL_CALL
        )

    def test_tool_call_with_none_returns_tool_call(self) -> None:
        assert (
            strictest_execution_path(ExecutionPath.TOOL_CALL, None) is ExecutionPath.TOOL_CALL
        )
        assert (
            strictest_execution_path(None, ExecutionPath.TOOL_CALL) is ExecutionPath.TOOL_CALL
        )

    @pytest.mark.parametrize("substrate", _PATHS)
    def test_mixing_tool_call_with_a_substrate_path_fails_closed(
        self, substrate: ExecutionPath
    ) -> None:
        with pytest.raises(ExecutionPathSelectionError):
            strictest_execution_path(ExecutionPath.TOOL_CALL, substrate)
        with pytest.raises(ExecutionPathSelectionError):
            strictest_execution_path(substrate, ExecutionPath.TOOL_CALL)

    @pytest.mark.parametrize("substrate", _PATHS)
    def test_is_strictly_stricter_than_refuses_tool_call(
        self, substrate: ExecutionPath
    ) -> None:
        with pytest.raises(ExecutionPathSelectionError):
            is_strictly_stricter_than(ExecutionPath.TOOL_CALL, substrate)
        with pytest.raises(ExecutionPathSelectionError):
            is_strictly_stricter_than(substrate, ExecutionPath.TOOL_CALL)


# ---------------------------------------------------------------------------
# Algebraic properties (small deterministic property tests without hypothesis)
# ---------------------------------------------------------------------------


class TestAlgebraicProperties:
    @pytest.mark.parametrize(
        "a,b",
        list(product(_PATHS, _PATHS)),
    )
    def test_commutative(self, a: ExecutionPath, b: ExecutionPath) -> None:
        assert strictest_execution_path(a, b) is strictest_execution_path(b, a)

    @pytest.mark.parametrize(
        "a,b,c",
        list(product(_PATHS, _PATHS, _PATHS)),
    )
    def test_associative(self, a: ExecutionPath, b: ExecutionPath, c: ExecutionPath) -> None:
        left = strictest_execution_path(strictest_execution_path(a, b), c)
        right = strictest_execution_path(a, strictest_execution_path(b, c))
        assert left is right

    @pytest.mark.parametrize(
        "a,b",
        list(product(_PATHS, _PATHS)),
    )
    def test_output_is_never_lower_than_maximum_input(
        self, a: ExecutionPath, b: ExecutionPath
    ) -> None:
        """The R7 core promise: an axis MAY raise the path, never
        lower it. That means the combinator's output is either equal
        to or strictly stricter than each input."""
        out = strictest_execution_path(a, b)
        # out is at least as strict as a AND at least as strict as b.
        assert not is_strictly_stricter_than(a, out)
        assert not is_strictly_stricter_than(b, out)

    @pytest.mark.parametrize(
        "a,b",
        list(product(_PATHS, _PATHS)),
    )
    def test_output_is_one_of_the_inputs(self, a: ExecutionPath, b: ExecutionPath) -> None:
        """The combinator never fabricates a third path."""
        assert strictest_execution_path(a, b) in {a, b}


# ---------------------------------------------------------------------------
# Fold over a variable-length axis list (roadmap: axes reduce pair-by-pair).
# ---------------------------------------------------------------------------


def _fold(paths: list[ExecutionPath | None]) -> ExecutionPath:
    """Reduce a list of axis outputs via the combinator, mirroring the
    RiskGate's ceiling-resolution fold."""
    from functools import reduce

    return reduce(strictest_execution_path, paths)  # type: ignore[arg-type]


class TestAxisFold:
    def test_fold_over_all_three_yields_pr_manual(self) -> None:
        assert (
            _fold(
                [
                    ExecutionPath.DIRECT_API,
                    ExecutionPath.PR_NATIVE,
                    ExecutionPath.PR_MANUAL,
                ]
            )
            is ExecutionPath.PR_MANUAL
        )

    def test_fold_with_none_axis_reduces_correctly(self) -> None:
        assert (
            _fold(
                [
                    ExecutionPath.DIRECT_API,
                    None,
                    ExecutionPath.PR_NATIVE,
                ]
            )
            is ExecutionPath.PR_NATIVE
        )

    def test_fold_of_all_direct_api_stays_direct_api(self) -> None:
        # No axis raises -> the ActionType default wins (R7: axes only
        # raise, never lower).
        assert (
            _fold(
                [
                    ExecutionPath.DIRECT_API,
                    ExecutionPath.DIRECT_API,
                    ExecutionPath.DIRECT_API,
                ]
            )
            is ExecutionPath.DIRECT_API
        )
