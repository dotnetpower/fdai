from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from fdai.core.rbac.resolver import GroupMapping, RoleResolver
from fdai.core.trajectory import (
    AllowlistTrajectoryAccessAuthorizer,
    InMemoryTrajectoryDatasetStore,
    TrajectoryDatasetAdminService,
    trajectory_scope_digest,
)
from fdai.delivery.read_api.app.config import ReadApiConfig
from fdai.delivery.read_api.app.factory import build_app
from fdai.delivery.read_api.auth import Authenticator, build_authenticator
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.shared.providers.trajectory import TrajectoryDatasetRecord, TrajectoryDatasetState

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


def _authenticator(role: str = "Owner") -> Authenticator:
    placeholder = "00000000-0000-0000-0000-000000000000"
    return build_authenticator(
        verifier=lambda _: {"oid": "owner-example", "roles": [role]},
        resolver=RoleResolver(
            group_mapping=GroupMapping(
                reader_group_id=placeholder,
                contributor_group_id=placeholder,
                approver_group_id=placeholder,
                owner_group_id=placeholder,
                break_glass_group_id=placeholder,
            )
        ),
    )


async def test_admin_api_is_owner_gated_get_only_and_purpose_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")
    store = InMemoryTrajectoryDatasetStore()
    await store.put(
        TrajectoryDatasetRecord(
            dataset_id="dataset-1",
            purpose="quality-review",
            access_scope="scope-example",
            principal_scope_digest=trajectory_scope_digest("scope-example"),
            state=TrajectoryDatasetState.COMPLETED,
            schema_version="1.0",
            storage_ref="dataset:private-location",
            record_count=2,
            dataset_checksum="b" * 64,
            manifest_checksum="c" * 64,
            created_at=NOW,
            retention_until=NOW + timedelta(days=30),
            deletion_due_at=NOW + timedelta(days=31),
        )
    )
    app = build_app(
        authenticator=_authenticator(),
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            trajectory_datasets=TrajectoryDatasetAdminService(
                authorizer=AllowlistTrajectoryAccessAuthorizer(
                    {"owner-example": frozenset({("scope-example", "quality-review")})}
                ),
                store=store,
            ),
        ),
    )
    headers = {"Authorization": "Bearer verified-owner"}

    with TestClient(app) as client:
        missing = client.get("/admin/trajectory-datasets", headers=headers)
        read = client.get(
            "/admin/trajectory-datasets?purpose=quality-review&access_scope=scope-example",
            headers=headers,
        )
        denied = client.get(
            "/admin/trajectory-datasets?purpose=quality-review&access_scope=other-scope",
            headers=headers,
        )
        mutation = client.post(
            "/admin/trajectory-datasets?purpose=quality-review&access_scope=scope-example",
            headers=headers,
        )

    assert missing.status_code == 400
    assert read.status_code == 200
    payload = read.json()
    assert payload["read_only"] is True
    assert payload["training_actions_available"] is False
    assert payload["promotion_actions_available"] is False
    assert payload["datasets"][0]["available"] is True
    assert "storage_ref" not in payload["datasets"][0]
    assert denied.status_code == 404
    assert mutation.status_code == 405


def test_admin_api_rejects_non_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FDAI_READ_API_DEV_MODE", "1")
    app = build_app(
        authenticator=_authenticator("Reader"),
        read_model=InMemoryConsoleReadModel(),
        config=ReadApiConfig(
            dev_mode=True,
            trajectory_datasets=TrajectoryDatasetAdminService(
                authorizer=AllowlistTrajectoryAccessAuthorizer(
                    {"owner-example": frozenset({("scope-example", "quality-review")})}
                ),
                store=InMemoryTrajectoryDatasetStore(),
            ),
        ),
    )

    with TestClient(app) as client:
        response = client.get(
            "/admin/trajectory-datasets?purpose=quality-review&access_scope=scope-example",
            headers={"Authorization": "Bearer verified-reader"},
        )

    assert response.status_code == 403
