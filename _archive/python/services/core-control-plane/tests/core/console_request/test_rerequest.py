"""Tests for the operator re-request gate (Scenario B).

Locks the one safety rule: a prior deny is authoritative (an operator cannot
override it by re-asking), while a prior no-op / no prior verdict lets the
request proceed to be judged fresh.
"""

from __future__ import annotations

from fdai.core.console_request.rerequest import (
    PriorRequestOutcome,
    RerequestRefusal,
    evaluate_operator_rerequest,
)


class TestRefused:
    def test_prior_deny_blocks_rerequest(self) -> None:
        d = evaluate_operator_rerequest(prior_outcome=PriorRequestOutcome.DENIED)
        assert not d.allowed
        assert d.refusal is RerequestRefusal.DENY_OVERRIDE_FORBIDDEN


class TestAllowed:
    def test_prior_no_op_allows_rerequest(self) -> None:
        d = evaluate_operator_rerequest(prior_outcome=PriorRequestOutcome.NO_OP)
        assert d.allowed
        assert d.refusal is None

    def test_no_prior_verdict_allows_request(self) -> None:
        d = evaluate_operator_rerequest(prior_outcome=PriorRequestOutcome.NONE)
        assert d.allowed
        assert d.refusal is None


class TestExhaustive:
    def test_only_deny_is_refused(self) -> None:
        # Every modeled outcome except DENIED is allowed; keeps the deny block
        # the single authoritative refusal.
        for outcome in PriorRequestOutcome:
            decision = evaluate_operator_rerequest(prior_outcome=outcome)
            if outcome is PriorRequestOutcome.DENIED:
                assert not decision.allowed
            else:
                assert decision.allowed
