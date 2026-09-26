"""Authenticated narrator Settings routes over the revisioned state/proposal seam."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import cast

import pytest
from fdai_operator_service.families.iam.contracts import IamPrincipal, ModelPreferenceCommand
from fdai_operator_service.families.iam.errors import IamConflictError
from fdai_operator_service.families.iam.settings import make_model_settings_routes
from fdai_operator_service.model_lifecycle_startup import (
    ConfiguredResolvedModelsSource,
    OperatorResolvedModelsRevisionOwner,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
    PostgresProposalConflict,
    StoredProposal,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters
from fdai_service_contracts import OperatorRole
from httpx import Response
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.testclient import TestClient


def _revision(*deployments: str) -> OperatorResolvedModelsRevisionOwner:
    content = json.dumps(
        {
            "capabilities": [],
            "narrator_candidates": [
                {
                    "endpoint": "https://example.openai.azure.com",
                    "deployment": deployment,
                }
                for deployment in deployments
            ],
        },
        sort_keys=True,
    )
    owner = OperatorResolvedModelsRevisionOwner(
        source=ConfiguredResolvedModelsSource(content),
        expected_digest=hashlib.sha256(content.encode()).hexdigest(),
    )
    asyncio.run(owner.start())
    return owner


class DurableStateFake(PostgresFamilyStore):
    """Exercise the real state/proposal call shape with atomic CAS and shared restart data."""

    def __init__(self) -> None:
        super().__init__(PostgresFamilyStoreConfig(dsn="postgresql://example.invalid/fdai"))
        self.states: dict[str, dict[str, object]] = {}
        self.audit: list[dict[str, object]] = []
        self.lock = asyncio.Lock()

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        assert (family, operation) == ("iam", "model-settings")
        return {
            "web_search": {},
            "environment": "dev",
            "narrator": {
                "selection_scope": "per-user",
                "revision": 99,
                "requested": "untrusted",
                "effective": "untrusted",
                "fallback_reason": None,
                "current_auto_pick": "untrusted",
                "candidates": [
                    {"deployment": "pinned", "family": "mini", "endpoint": "must-not-leak"},
                    {"deployment": "untrusted", "family": "mini"},
                ],
            },
        }

    async def read_state(self, key: str) -> dict[str, object] | None:
        return self.states.get(key)

    async def append_revisioned_proposal(
        self,
        *,
        family: str,
        operation: str,
        principal_id: str | None,
        idempotency_key: str,
        payload: Mapping[str, object],
        state_key: str,
        state_value: Mapping[str, object],
        expected_revision: int,
    ) -> StoredProposal:
        assert (family, operation) == ("iam", "model-settings.preference")
        assert principal_id is not None and idempotency_key
        async with self.lock:
            current = self.states.get(state_key)
            if (current["revision"] if current else 0) != expected_revision:
                raise PostgresProposalConflict("state revision conflict")
            self.states[state_key] = dict(state_value)
            self.audit.append({"principal_id": principal_id, "payload": dict(payload)})
        return StoredProposal("proposal-1", "2026-09-26T00:00:00Z", False, {})


def _client(store: DurableStateFake, owner: OperatorResolvedModelsRevisionOwner) -> TestClient:
    async def authorize(request: Request) -> IamPrincipal:
        principal = request.headers.get("x-verified-oid")
        if not principal:
            raise HTTPException(status_code=401, detail="authentication required")
        return IamPrincipal(principal, frozenset({OperatorRole.READER}))

    return TestClient(
        Starlette(
            routes=make_model_settings_routes(
                outbox=PostgresIamAdapters(store, narrator_revision_owner=owner),
                authorize=authorize,
            )
        )
    )


def _write(client: TestClient, principal: str, deployment: str, revision: int) -> Response:
    return cast(
        Response,
        client.put(
            "/me/model-preferences",
            headers={"x-verified-oid": principal},
            json={"preferred_narrator_model": deployment, "expected_revision": revision},
        ),
    )


def _read(client: TestClient, principal: str) -> dict[str, object]:
    response = client.get("/models/settings", headers={"x-verified-oid": principal})
    assert response.status_code == 200, response.text
    narrator: dict[str, object] = response.json()["narrator"]
    return narrator


def test_authenticated_route_isolated_durable_and_revision_fenced() -> None:
    store = DurableStateFake()
    owner = _revision("pinned", "other")
    first = _client(store, owner)
    assert first.put("/me/model-preferences", json={}).status_code == 401
    assert first.get("/models/settings").status_code == 401
    assert _write(first, "principal-a", "arbitrary", 0).status_code == 400
    assert (
        first.put(
            "/me/model-preferences",
            headers={"x-verified-oid": "principal-a"},
            json={"preferred_narrator_model": "pinned", "expected_revision": True},
        ).status_code
        == 400
    )
    created = _write(first, "principal-a", "pinned", 0)
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    assert _write(first, "principal-a", "other", 0).status_code == 409
    assert _write(first, "principal-a", "pinned", 0).status_code == 409
    assert _write(first, "principal-b", "other", 0).status_code == 200
    assert _read(first, "principal-b")["requested"] == "other"

    restarted = _client(store, _revision("pinned", "other"))
    a = _read(restarted, "principal-a")
    b = _read(restarted, "principal-b")
    assert (a["revision"], a["requested"], a["effective"]) == (1, "pinned", "pinned")
    assert (b["revision"], b["requested"], b["effective"]) == (1, "other", "other")
    assert a["selection_scope"] == "per-user"
    assert a["personalizes_t2_bindings"] is False
    assert "untrusted" not in json.dumps(a)
    assert "must-not-leak" not in json.dumps(a)
    assert len(store.audit) == 2
    assert {record["principal_id"] for record in store.audit} == {"principal-a", "principal-b"}
    payload = store.audit[0]["payload"]
    assert isinstance(payload, dict)
    assert payload["source_revision"] == owner.expected_digest


def test_removed_deployment_falls_back_without_erasing_choice() -> None:
    store = DurableStateFake()
    first = _client(store, _revision("pinned", "other"))
    assert _write(first, "principal-a", "pinned", 0).status_code == 200
    removed = _client(store, _revision("other"))
    projection = _read(removed, "principal-a")
    assert (projection["requested"], projection["effective"], projection["revision"]) == (
        "pinned",
        "auto",
        1,
    )
    assert projection["fallback_reason"] == "deployment_unavailable"
    assert _write(removed, "principal-a", "pinned", 1).status_code == 400
    assert _write(removed, "principal-a", "auto", 1).status_code == 200
    assert _read(removed, "principal-a")["requested"] == "auto"


def test_empty_startup_pool_degrades_existing_choice_to_auto() -> None:
    store = DurableStateFake()
    first = _client(store, _revision("pinned"))
    assert _write(first, "principal-a", "pinned", 0).status_code == 200
    empty = _client(store, _revision())
    projection = _read(empty, "principal-a")
    assert projection["effective"] == "auto"
    assert projection["requested"] == "pinned"
    assert projection["candidates"] == []
    assert _write(empty, "principal-a", "auto", 1).status_code == 200


def test_concurrent_writes_have_one_cas_winner() -> None:
    store = DurableStateFake()
    owner = _revision("pinned", "other")
    adapter = PostgresIamAdapters(store, narrator_revision_owner=owner)

    async def race() -> tuple[BaseException | None, BaseException | None]:
        return await asyncio.gather(
            adapter.set_preference(ModelPreferenceCommand("principal-a", "pinned", 0)),
            adapter.set_preference(ModelPreferenceCommand("principal-a", "other", 0)),
            return_exceptions=True,
        )

    results = asyncio.run(race())
    assert sum(isinstance(result, IamConflictError) for result in results) == 1
    assert sum(result is None for result in results) == 1
    assert len(store.audit) == 1


def test_startup_digest_and_choice_source_cannot_be_substituted() -> None:
    owner = _revision("pinned")
    assert owner.narrator_allowlist() == ("pinned",)
    owner.source = _revision("other").source
    assert owner.narrator_allowlist() == ("pinned",)
    owner.expected_digest = "0" * 64
    with pytest.raises(ValueError, match="deployment binding"):
        asyncio.run(
            OperatorResolvedModelsRevisionOwner(
                source=owner.source, expected_digest=owner.expected_digest
            ).start()
        )
    store = DurableStateFake()
    client = _client(store, _revision("other"))
    assert _write(client, "principal-a", "pinned", 0).status_code == 400
    assert not store.audit


def test_unstarted_or_unconfigured_revision_never_accepts_a_pin() -> None:
    store = DurableStateFake()
    owner = _revision("pinned")
    owner.revision = None
    client = _client(store, owner)
    assert _write(client, "principal-a", "pinned", 0).status_code == 503
    assert not store.audit


def test_ambiguous_startup_deployment_is_not_selectable() -> None:
    store = DurableStateFake()
    client = _client(store, _revision("pinned", "pinned"))
    assert _write(client, "principal-a", "pinned", 0).status_code == 503
    assert not store.audit
