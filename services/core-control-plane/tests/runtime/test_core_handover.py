"""Core source and governed-reader construction performs no provider I/O or authority change."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.runtime.core_handover import CurrentCoreHandoverSource, build_core_handover_services
from fdai.runtime.handover_document_reader import CoreHandoverDocumentReader
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.workload_identity import IdentityToken

ROOT = Path(__file__).resolve().parents[4]
AT = datetime(2026, 9, 14, 12, tzinfo=UTC)
PERSON = "00000000-0000-0000-0000-000000000001"
GROUP = "00000000-0000-0000-0000-000000000002"


async def test_actual_core_read_binding_has_no_constructor_provider_io_and_uses_current_roles():
    requests = []

    async def handler(request):
        requests.append(request)
        assert request.method == "GET"
        if request.url.path == f"/v1.0/users/{PERSON}":
            return httpx.Response(200, json={"id": PERSON, "accountEnabled": True})
        if request.url.path == f"/v1.0/groups/{GROUP}":
            return httpx.Response(200, json={"id": GROUP, "displayName": "Example Owners"})
        if request.url.path.endswith("/transitiveMembers/microsoft.graph.user"):
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": PERSON,
                            "displayName": "Example person",
                            "userPrincipalName": "person@example.com",
                            "accountEnabled": True,
                        }
                    ]
                },
            )
        return httpx.Response(404)

    identity = SimpleNamespace(
        get_token=AsyncMock(
            return_value=IdentityToken(
                "synthetic-token",
                AT + timedelta(minutes=10),
                "https://graph.microsoft.com/.default",
            )
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        core = build_core_handover_services(
            store=InMemoryStateStore(),
            catalog_root=ROOT / "rule-catalog",
            http_client=client,
            identity=identity,
            clock=lambda: AT,
            environment={
                "FDAI_STATE_STORE_DSN": "host=127.0.0.1 dbname=example",
                "FDAI_RBAC_OWNERS_GROUP_ID": GROUP,
            },
        )
        assert core is not None and not requests
        identity.get_token.assert_not_called()
        assert (await core.admission.identities.read(PERSON)).subject_ref == PERSON
        assert await core.admission.may_review(
            reviewer_ref=PERSON, agent_name="Muninn", scope_ref="scope:example", role="owner"
        )
        assert sum(request.url.path == f"/v1.0/groups/{GROUP}" for request in requests) == 2
        assert core.admission.identities.directory.roster_cache_seconds == 0
        assert core.admission.identities.directory.max_attempts == 1


async def test_missing_core_bindings_never_satisfy_current_source_contribution():
    assert (
        build_core_handover_services(
            store=InMemoryStateStore(),
            environment={},
            catalog_root=None,
            http_client=None,
            identity=None,
        )
        is None
    )
    source = SimpleNamespace(contribution_current=AsyncMock(return_value=True))
    with pytest.raises(ValueError, match="bindings are unavailable"):
        await CurrentCoreHandoverSource(source, None).contribution_current(
            SimpleNamespace(source="core")
        )
    assert await CurrentCoreHandoverSource(source, None).contribution_current(
        SimpleNamespace(source="operator")
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"purpose": "execute"},
        {"principal_role": "BreakGlass"},
        {"principal_ref": ""},
        {"limit": True},
        {"limit": 9},
        {"query": ""},
    ],
)
async def test_governed_read_context_is_checked_before_any_source_io(changes):
    source = SimpleNamespace(_connect=AsyncMock())
    reader = CoreHandoverDocumentReader(SimpleNamespace(source=source))
    with pytest.raises(PermissionError):
        await reader.search(
            **{
                "query": "rollback",
                "principal_ref": PERSON,
                "principal_role": CeilingRole.READER,
                "principal_groups": frozenset(),
                "purpose": "operations-review",
                "limit": 8,
                **changes,
            }
        )
    source._connect.assert_not_awaited()
