"""The demo's generated files plan as the scenario expects, using the Hub's own code."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.runtime_release import parse_runtime_release_manifest
from lifecycle.demo import catalog
from lifecycle.demo.catalog import ENTITY, INSTALLATION_ID, MIRROR, RELEASES, Layout

from fdai_lifecycle_hub import schemas
from fdai_lifecycle_hub.catalog import load_catalog
from fdai_lifecycle_hub.domain import Issued, IssuedPlan, UpToDate, Waiting
from fdai_lifecycle_hub.planning import plan_next
from fdai_lifecycle_hub.signing import (
    load_private_key,
    load_public_key,
    load_signing_key,
    verify_key_proof,
)
from fdai_lifecycle_hub.store import HubStore

# Inside the demo's 00:00 and 12:00 UTC windows.
NOW = datetime(2026, 10, 9, 1, tzinfo=UTC)


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    layout = Layout(tmp_path / "demo")
    catalog.prepare(layout, now=NOW - timedelta(minutes=5))
    return layout


@pytest.fixture
def store(tmp_path: Path) -> Iterator[HubStore]:
    hub = HubStore.connect(f"sqlite+pysqlite:///{tmp_path / 'hub.db'}")
    hub.create_schema()
    yield hub
    hub.engine.dispose()


def _json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def test_releases_are_valid_and_signed_and_their_images_are_available(layout: Layout) -> None:
    entities = _json(layout.current_state)["entities"]
    available = set(entities[MIRROR]["artifact_digests"])

    for release in RELEASES:
        payload = (layout.catalog / "releases" / f"{release.release_id}.json").read_bytes()
        parsed = parse_runtime_release_manifest(payload)
        signed = layout.inputs / "releases" / f"{parsed.digest}.json"
        signature = signed.with_suffix(".sig").read_bytes()
        load_public_key(layout.public_key("release")).verify(signature, signed.read_bytes())
        assert signed.read_bytes() == payload
        images = {
            record["image_digest"]
            for section in ("services", "sidecars", "installation_agents")
            for record in json.loads(payload)[section].values()
        }
        assert images == {release.image_digest} <= available
    assert len({release.image_digest for release in RELEASES}) == 3
    assert entities[ENTITY]["artifact_digests"] == []


def test_state_digest_is_the_canonical_digest_of_the_rest(layout: Layout) -> None:
    state = _json(layout.current_state)
    digest = state.pop("digest")

    assert digest == canonical_digest(state)
    assert state["entities"][ENTITY]["release_id"] == catalog.INITIAL_RELEASE
    assert _json(layout.enrollment)["reported"]["digest"] == digest


def test_publish_adds_one_known_release_at_a_time(layout: Layout) -> None:
    assert _json(layout.channels) == {catalog.CHANNEL: []}
    assert catalog.publish(layout, "1.1.0") == ["1.1.0"]
    assert catalog.publish(layout, "1.0.0") == ["1.0.0", "1.1.0"]
    assert catalog.publish(layout, "1.0.0") == ["1.0.0", "1.1.0"]
    with pytest.raises(ValueError, match="not a demo Release"):
        catalog.publish(layout, "9.9.9")


def test_reset_removes_only_a_demo_directory(tmp_path: Path, layout: Layout) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("keep")

    catalog.reset(layout.root)
    with pytest.raises(ValueError, match="wasn't created by the demo"):
        catalog.reset(foreign)

    assert not layout.root.exists()
    assert (foreign / "keep.txt").exists()


def test_local_policy_names_the_image_repository_only_for_apply() -> None:
    assert "component_images" not in catalog.local_policy(apply=False)
    assert catalog.local_policy(apply=True)["component_images"] == {
        catalog.COMPONENT: catalog.IMAGE_REPOSITORY
    }


def _report(plan: IssuedPlan, attempt: int, outcome: str, reason: str) -> schemas.PlanReport:
    return schemas.PlanReport.model_validate(
        {
            "attempt": attempt,
            "outcome": outcome,
            "reason_code": reason,
            "exact_plan_digest": plan.digest,
            "summary": "",
            "reported_at": NOW.isoformat(),
        }
    )


def test_hub_plans_the_scenario_and_holds_core_after_the_rollback(
    layout: Layout, store: HubStore
) -> None:
    """Stand in for the applying agent: report the apply results and the new state."""

    template = _json(layout.enrollment)
    request = schemas.sign_enrollment(template, load_private_key(layout.key("installation")), NOW)
    store.request_enrollment(request, verify=verify_key_proof, now=NOW)
    key_id = request.installation_key_id
    store.approve(INSTALLATION_ID, approver="approver", installation_key_id=key_id, now=NOW)
    ownership = schemas.ownership_json.validate_json(layout.ownership.read_bytes())
    store.record_ownership(INSTALLATION_ID, ENTITY, ownership, operator="operator", now=NOW)
    settings = schemas.entity_settings_json.validate_json(layout.settings.read_bytes())
    store.manage(INSTALLATION_ID, ENTITY, settings, operator="operator", now=NOW)
    key = load_signing_key(layout.key("hub"), epoch=1)

    def recompute(at: datetime) -> object:
        planner = partial(plan_next, catalog=load_catalog(layout.catalog), key=key)
        return store.recompute(INSTALLATION_ID, planner, now=at)

    running = catalog.INITIAL_RELEASE
    images: list[str] = []
    for minute, release in enumerate(RELEASES, start=1):
        at = NOW + timedelta(minutes=minute)
        catalog.publish(layout, release.release_id)
        issued = recompute(at)
        assert isinstance(issued, Issued)
        assert issued.plan.target_release_id == release.release_id
        plan = IssuedPlan.from_signed(issued.plan)
        failed = release.release_id == "1.2.0"
        record = partial(store.record_report, INSTALLATION_ID, plan.plan_id, now=at)
        record(_report(plan, 1, "apply-started", "apply_started"))
        record(
            _report(plan, 2, "rolled-back", "health_check_failed")
            if failed
            else _report(plan, 2, "applied", "applied")
        )
        if not failed:
            running, images = release.release_id, [release.image_digest]
        # Like the agent: `core` reports the image it runs, and the mirror stays unchanged.
        snapshot = catalog.state_snapshot(running, images, "healthy", at)
        state = schemas.reported_state_json.validate_python(snapshot)
        store.record_state(INSTALLATION_ID, state, now=at)

        after = recompute(at)
        assert isinstance(after, Waiting if failed else UpToDate)

    assert running == "1.1.0"
    assert store.current_plan(INSTALLATION_ID, now=NOW + timedelta(hours=1)) is None
    (hold,) = store.load(INSTALLATION_ID).suppressions
    assert (hold.scope, hold.origin, hold.failed_plan_id) == (
        f"entity:{ENTITY}",
        "failure",
        f"{INSTALLATION_ID}-00000003",
    )
