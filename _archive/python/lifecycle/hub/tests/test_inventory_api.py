from __future__ import annotations

from dataclasses import replace

import pytest
from fdai_deployment_cli.runtime_release import RecallRecord
from starlette.testclient import TestClient

from fdai_lifecycle_hub.api import create_app
from fdai_lifecycle_hub.catalog import ReleaseCatalog
from fdai_lifecycle_hub.enrollment import EnrollmentStatus
from fdai_lifecycle_hub.inventory import release_inventory
from fdai_lifecycle_hub.signing import verify_key_proof


def test_configuration_inventory_is_metadata_only(store, installation, enroll):
    private_value = "private-configuration-value"
    installation = replace(
        installation,
        configuration=replace(
            installation.configuration,
            schema={
                **installation.configuration.schema,
                "private_marker": {"x-fdai-axis": "installation-path", "x-fdai-owner": "customer"},
            },
            environment={"private_marker": private_value},
        ),
    )
    enroll(store, installation)
    before = store.configuration_inventory()
    with TestClient(create_app(store)) as client:
        response = client.get("/v1/configurations")
        assert response.status_code == 200
        (revision,) = response.json()["configurations"]
        assert revision["digest"] == installation.configuration.digest
        assert revision["installation_ids"] == [installation.installation_id]
        assert revision["schema_key_count"] == len(installation.configuration.schema)
        assert revision["signature_status"] == "not-recorded"
        assert set(revision) == {
            "digest",
            "imported_at",
            "schema_key_count",
            "override_count",
            "installation_ids",
            "signature_status",
        }
        assert private_value not in response.text
        assert "private_marker" not in response.text
        assert client.post("/v1/configurations", json={}).status_code == 405
    assert store.configuration_inventory() == before


def test_configuration_inventory_empty_is_not_unavailable(store):
    with TestClient(create_app(store)) as client:
        assert client.get("/v1/configurations").json() == {"configurations": []}


@pytest.mark.parametrize("status", list(EnrollmentStatus))
def test_configuration_inventory_links_only_enrolled_installations(
    store, enrollment, now, status: EnrollmentStatus
):
    store.request_enrollment(enrollment, verify=verify_key_proof, now=now)
    installation_id = enrollment.installation.installation_id
    if status == EnrollmentStatus.ENROLLED:
        store.approve(
            installation_id,
            approver="approver",
            installation_key_id=enrollment.installation_key_id,
            now=now,
        )
    elif status == EnrollmentStatus.REJECTED:
        store.reject(installation_id, approver="approver", reason="operator_declined", now=now)

    with TestClient(create_app(store)) as client:
        response = client.get("/v1/configurations")
        assert response.status_code == 200
        (revision,) = response.json()["configurations"]
        assert revision["digest"] == enrollment.installation.configuration.digest
        assert revision["signature_status"] == "not-recorded"
        assert revision["installation_ids"] == (
            [installation_id] if status == EnrollmentStatus.ENROLLED else []
        )
        assert client.get(f"/v1/installations/{installation_id}").status_code == (
            200 if status == EnrollmentStatus.ENROLLED else 404
        )


def test_release_inventory_preserves_recall_facts(catalog):
    notice = RecallRecord(scope="release", target="1.5.0", sequence=1, notice_digest="a" * 64)
    result = release_inventory(replace(catalog, recalls=(notice,)))
    selected = next(item for item in result["releases"] if item["release_id"] == "1.5.0")
    assert selected["recall_notices"][0]["action"] == "recall"
    assert selected["recall_notices"][0]["notice_digest"] == "a" * 64
    assert release_inventory(ReleaseCatalog(releases={}, channels={})) == {"releases": []}
