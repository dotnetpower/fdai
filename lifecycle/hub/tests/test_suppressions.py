from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.domain import Installation, Issued, Planner, Waiting
from fdai_lifecycle_hub.store import HubStore


def _window(now: datetime, scope: str = "installation", hours: int = 1) -> SuppressionWindow:
    return SuppressionWindow(scope, now, now + timedelta(hours=hours))


@pytest.mark.parametrize("scope", ["installation", "entity:core", "entity:console", "plan:upgrade"])
def test_known_scopes_are_accepted(installation: Installation, now: datetime, scope: str) -> None:
    assert installation.suppressed(_window(now, scope), now).suppressions == (_window(now, scope),)


@pytest.mark.parametrize("scope", ["entity:missing", "plan:deploy", "installation:x", "region"])
def test_unknown_scopes_are_rejected(installation: Installation, now: datetime, scope: str) -> None:
    with pytest.raises(ValueError, match="unknown suppression scope"):
        installation.suppressed(_window(now, scope), now)


def test_a_suppression_must_end_in_the_future(installation: Installation, now: datetime) -> None:
    past = SuppressionWindow("installation", now - timedelta(hours=2), now - timedelta(hours=1))

    with pytest.raises(ValueError, match="end in the future"):
        installation.suppressed(past, now)


def test_adding_drops_expired_windows(installation: Installation, now: datetime) -> None:
    expired = SuppressionWindow("installation", now - timedelta(hours=2), now - timedelta(hours=1))
    stale = replace(installation, suppressions=(expired,))

    assert stale.suppressed(_window(now), now).suppressions == (_window(now),)


def test_lifting_removes_only_that_scope(installation: Installation, now: datetime) -> None:
    both = installation.suppressed(_window(now), now).suppressed(_window(now, "entity:core"), now)

    assert both.lifted("installation", now).suppressions == (_window(now, "entity:core"),)
    with pytest.raises(ValueError, match="no active suppression"):
        installation.lifted("installation", now)


def test_suppression_withdraws_the_plan_until_lifted(
    store: HubStore, installation: Installation, planner: Planner, now: datetime
) -> None:
    store.register(installation, now=now)
    first = store.recompute(installation.installation_id, planner, now=now)
    client = TestClient(create_app(store, clock=lambda: now))
    plan_url = f"/v1/installations/{installation.installation_id}/plan"

    store.add_suppression(installation.installation_id, _window(now), now=now)
    withdrawn = client.get(plan_url).status_code
    held = store.recompute(installation.installation_id, planner, now=now)
    store.lift_suppressions(installation.installation_id, "installation", now=now)
    reissued = store.recompute(installation.installation_id, planner, now=now)

    assert isinstance(first, Issued)
    assert withdrawn == 204
    assert isinstance(held, Waiting)
    assert held.checks[0].blocks[0].reason_code == "suppression_window_active"
    assert isinstance(reissued, Issued)
    assert reissued.plan.sequence == 2
    assert store.load(installation.installation_id).suppressions == ()
    assert store.audit_chain_intact()


def test_future_suppression_keeps_the_open_plan(
    store: HubStore, installation: Installation, planner: Planner, now: datetime
) -> None:
    store.register(installation, now=now)
    store.recompute(installation.installation_id, planner, now=now)
    later = SuppressionWindow("installation", now + timedelta(hours=3), now + timedelta(hours=4))

    store.add_suppression(installation.installation_id, later, now=now)

    assert store.current_plan(installation.installation_id, now=now) is not None
