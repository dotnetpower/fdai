"""Read-time join of the MCSB shadow assessment onto the MCSB catalog read."""

from __future__ import annotations

import asyncio

import pytest
from fdai_operator_service.framework_mcsb_assessment_projection import (
    MCSB_ASSESSMENT_PROJECTION_KEY,
    attach_mcsb_assessment,
)
from starlette.exceptions import HTTPException


class _Reader:
    def __init__(self, value: object) -> None:
        self.value = value
        self.keys: list[str] = []

    async def read_state(self, key: str) -> object:
        self.keys.append(key)
        return self.value


def _projection(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "_revision": "sha256:" + "a" * 64,
        "framework_id": "azure-mcsb",
        "framework_version": "2026-07-29",
        "catalog_digest": "sha256:" + "b" * 64,
        "evaluation_source": "framework-shadow-assessment",
        "last_evaluated_at": "2026-10-08T00:00:00+00:00",
        "controls": [
            {
                "control_id": "NS-2",
                "applicability": "applicable",
                "evaluation_status": "evaluated",
                "satisfaction": "failed",
                "evaluated_at": "2026-10-08T00:00:00+00:00",
                "evidence_complete": False,
                "limitations": [],
                "requirements": [{"ref": "rule-a", "evidence_role": "decisive"}],
                "execution_authority": False,
            }
        ],
    }
    value.update(changes)
    return value


def _list_payload(version: str = "v1") -> dict[str, object]:
    return {
        "benchmark": {"benchmark_version": version},
        "controls": [{"control_id": "NS-2"}, {"control_id": "NS-3"}],
    }


def test_list_attaches_server_owned_control_state() -> None:
    reader = _Reader(_projection())

    payload, revision = asyncio.run(attach_mcsb_assessment(_list_payload(), reader, detail=False))

    assert reader.keys == [MCSB_ASSESSMENT_PROJECTION_KEY]
    assert revision is not None
    assert payload["controls"][0]["assessment"]["satisfaction"] == "failed"
    assert "requirements" not in payload["controls"][0]["assessment"]
    assert payload["controls"][1]["assessment"] is None
    summary = payload["assessment_summary"]
    assert summary["status"] == "evaluated"
    assert summary["satisfaction_counts"] == {"failed": 1}
    assert summary["execution_authority"] is False


def test_detail_carries_requirements_with_roles() -> None:
    detail, _ = asyncio.run(
        attach_mcsb_assessment(
            {"benchmark_version": "v1", "control_id": "NS-2"}, _Reader(_projection()), detail=True
        )
    )

    assert detail["assessment"]["requirements"] == [{"ref": "rule-a", "evidence_role": "decisive"}]


def test_missing_projection_and_unassessed_versions_read_without_state() -> None:
    missing, missing_revision = asyncio.run(
        attach_mcsb_assessment(_list_payload(), _Reader(None), detail=False)
    )
    preview, preview_revision = asyncio.run(
        attach_mcsb_assessment(_list_payload("v2-preview"), _Reader(_projection()), detail=False)
    )

    assert missing_revision is None and preview_revision is None
    assert missing["assessment_summary"]["status"] == "unavailable"
    assert preview["assessment_summary"]["status"] == "not_assessed"
    assert all(item["assessment"] is None for item in missing["controls"])


@pytest.mark.parametrize(
    "projection",
    [
        _projection(framework_id="azure-caf"),
        _projection(_revision=""),
        _projection(controls="broken"),
        _projection(
            controls=[{"control_id": "NS-2", "execution_authority": True}],
        ),
        _projection(
            controls=[
                {"control_id": "NS-2", "execution_authority": False},
                {"control_id": "NS-2", "execution_authority": False},
            ],
        ),
    ],
)
def test_malformed_or_authority_bearing_projection_fails_closed(
    projection: dict[str, object],
) -> None:
    with pytest.raises(HTTPException) as raised:
        asyncio.run(attach_mcsb_assessment(_list_payload(), _Reader(projection), detail=False))
    assert raised.value.status_code == 503
