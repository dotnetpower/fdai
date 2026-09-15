"""Only Owner can read a current lifecycle report; unavailable evidence never becomes health."""

from __future__ import annotations

import runpy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fdai_operator_service.families.iam.contracts import IamPrincipal
from fdai_operator_service.families.iam.errors import IamUnavailableError
from fdai_operator_service.families.iam.handover import make_handover_routes
from fdai_service_contracts import OperatorRole
from fdai_service_contracts.handover_readiness import (
    HANDOVER_READINESS_KEY,
    HandoverReadinessReport,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient

_support = runpy.run_path(str(Path(__file__).with_name("test_handover_runtime.py")))
NOW, runtime_fixture = _support["_NOW"], _support["_runtime"]


def _report():
    return HandoverReadinessReport(
        revision=1,
        observed_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
        enabled=True,
        sample_limit=100,
        cases_observed=0,
        cases_total=0,
        cases_invalid=0,
        cases_by_state={},
        knowledge_observed=0,
        knowledge_total=0,
        knowledge_invalid=0,
        knowledge_by_disposition={},
        partial=False,
        convergence_samples=0,
        mean_effect_interval_seconds=None,
        alerts=(),
        source_gaps=("group_schedule_scoped_effective_date_realization",),
        external_blockers=("independent_promotion_cohorts",),
    ).model_dump(mode="json")


@pytest.mark.parametrize("role", tuple(OperatorRole))
def test_readiness_role_boundary_precedes_any_durable_read(role):
    runtime, store, _ = runtime_fixture()
    store.states[HANDOVER_READINESS_KEY] = _report()

    async def authorize(request):
        return IamPrincipal("human:observer", frozenset({role}))

    client = TestClient(Starlette(routes=make_handover_routes(outbox=runtime, authorize=authorize)))
    response = client.get("/handover/readiness")
    assert response.status_code == (200 if role == OperatorRole.OWNER else 403)
    if role == OperatorRole.OWNER:
        assert response.json()["readiness"]["operationally_ready"] is False


@pytest.mark.parametrize("delta", [-1, 600, 601])
async def test_future_and_expired_report_is_unavailable(delta):
    runtime, store, _ = runtime_fixture()
    store.states[HANDOVER_READINESS_KEY] = _report()
    with pytest.raises(IamUnavailableError):
        await replace(runtime, clock=lambda: NOW + timedelta(seconds=delta)).lifecycle_readiness()


async def test_missing_and_malformed_report_never_become_zero():
    runtime, store, _ = runtime_fixture()
    with pytest.raises(IamUnavailableError):
        await runtime.lifecycle_readiness()
    store.states[HANDOVER_READINESS_KEY] = {**_report(), "cases_observed": 1}
    with pytest.raises(IamUnavailableError):
        await runtime.lifecycle_readiness()
