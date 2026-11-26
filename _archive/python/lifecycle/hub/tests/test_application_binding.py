from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from fdai_lifecycle_hub import audit, models
from fdai_lifecycle_hub.domain import Installation, Issued, Planner
from fdai_lifecycle_hub.execution_settings import ApplicationBindingRequest, ExecutionSettingsError
from fdai_lifecycle_hub.store import HubStore


def command(
    store: HubStore, identifier: str, product: str = "example-web"
) -> ApplicationBindingRequest:
    digest = store.execution_settings(identifier)["settings_digest"]
    return ApplicationBindingRequest.model_validate_json(
        json.dumps(
            {
                "request_id": str(uuid4()),
                "expected_settings_digest": digest,
                "product": product,
                "reason_code": "operator_application_binding",
                "confirmation": f"bind application {identifier} {product} {digest}",
            }
        )
    )


def test_binding_is_attributed_durable_and_retry_safe_without_granting_ownership(
    hub_store: HubStore,
    installation: Installation,
    enroll: Callable[[HubStore, Installation], None],
    now: datetime,
) -> None:
    enroll(hub_store, installation)
    identifier = installation.installation_id
    before = hub_store.load(identifier)
    request = command(hub_store, identifier)
    result = hub_store.bind_application(identifier, request, operator="owner", now=now)
    assert result["changed"] is True
    restarted = HubStore(hub_store.engine)
    after = restarted.load(identifier)
    assert after.settings == replace(before.settings, product="example-web")
    assert after.entities == before.entities
    assert after.configuration == before.configuration
    assert after.reported == before.reported
    assert restarted.current_plan(identifier, now=now) is None
    assert restarted.bind_application(identifier, request, operator="owner", now=now) == {
        "changed": False,
        "settings_digest": result["settings_digest"],
    }
    with Session(hub_store.engine) as session:
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "installation.application_bound"
            )
        ).all()
        assert len(records) == 1
        assert records[0].payload["operator"] == "owner"
        assert records[0].payload["product"] == "example-web"
        assert records[0].payload["request_digest"] == request.digest
        assert audit.chain_intact(session)


def test_binding_cannot_retarget_an_already_bound_installation(
    enrolled_store: HubStore, installation: Installation, now: datetime
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    store.bind_application(identifier, command(store, identifier), operator="owner", now=now)
    before = store.load(identifier)
    with pytest.raises(ExecutionSettingsError, match="already_bound"):
        store.bind_application(
            identifier, command(store, identifier, "different-app"), operator="owner", now=now
        )
    assert store.load(identifier) == before


def test_pending_plan_blocks_binding(
    enrolled_store: HubStore, installation: Installation, planner: Planner, now: datetime
) -> None:
    identifier = installation.installation_id
    request = command(enrolled_store, identifier)
    assert isinstance(enrolled_store.recompute(identifier, planner, now=now), Issued)
    with pytest.raises(ExecutionSettingsError, match="plan_pending"):
        enrolled_store.bind_application(identifier, request, operator="owner", now=now)
    assert enrolled_store.load(identifier).settings.product is None


@pytest.mark.parametrize("problem", ["revision", "confirmation", "actor", "request"])
def test_stale_or_conflicting_binding_changes_have_no_effect(
    enrolled_store: HubStore, installation: Installation, now: datetime, problem: str
) -> None:
    store, identifier = enrolled_store, installation.installation_id
    request = command(store, identifier)
    if problem in {"actor", "request"}:
        store.bind_application(identifier, request, operator="owner", now=now)
    if problem == "revision":
        request = request.model_copy(update={"expected_settings_digest": "f" * 64})
    if problem == "confirmation":
        request = request.model_copy(update={"confirmation": "not confirmed"})
    if problem == "request":
        request = request.model_copy(update={"reason_code": "different_request"})
    before = store.load(identifier)
    with pytest.raises(ExecutionSettingsError, match="conflict|confirmation_mismatch"):
        store.bind_application(
            identifier,
            request,
            operator="different-owner" if problem == "actor" else "owner",
            now=now,
        )
    assert store.load(identifier) == before


@pytest.mark.parametrize("field", ["operator", "windows", "fencing_generation", "entity_ids"])
def test_binding_request_cannot_modify_authority_or_scope(
    enrolled_store: HubStore, installation: Installation, field: str
) -> None:
    raw = command(enrolled_store, installation.installation_id).model_dump(mode="json")
    with pytest.raises(ValidationError):
        ApplicationBindingRequest.model_validate_json(json.dumps({**raw, field: "forged"}))


@pytest.mark.integration
def test_postgres_serializes_competing_application_bindings(
    hub_store: HubStore,
    installation: Installation,
    enroll: Callable[[HubStore, Installation], None],
    now: datetime,
) -> None:
    if hub_store.engine.dialect.name != "postgresql":
        pytest.skip("Concurrent row locking requires PostgreSQL.")
    enroll(hub_store, installation)
    identifier = installation.installation_id
    requests = [
        command(hub_store, identifier, product) for product in ("example-web", "example-api")
    ]
    before = hub_store.load(identifier)

    def bind(request: ApplicationBindingRequest) -> dict[str, object]:
        try:
            return HubStore(hub_store.engine).bind_application(
                identifier, request, operator="owner", now=now
            )
        except ExecutionSettingsError as error:
            return {"error": str(error)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(bind, requests))
    assert sum(result.get("changed") is True for result in results) == 1
    assert {"error": "application_binding_revision_conflict"} in results
    after = HubStore(hub_store.engine).load(identifier)
    assert after.settings.product in {"example-web", "example-api"}
    assert after.entities == before.entities
    assert after.reported == before.reported
    with Session(hub_store.engine) as session:
        records = session.scalars(
            select(models.AuditRecord).where(
                models.AuditRecord.action == "installation.application_bound"
            )
        ).all()
        assert len(records) == 1
        assert records[0].payload["product"] == after.settings.product
        assert audit.chain_intact(session)
