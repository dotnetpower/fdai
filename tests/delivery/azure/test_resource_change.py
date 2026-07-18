"""Azure Event Grid resource change normalization tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from fdai.delivery.azure.resource_change import normalize_resource_change_events
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping

_ROOT = Path(__file__).resolve().parents[3]
_VOCABULARY = _ROOT / "rule-catalog" / "vocabulary" / "resource-types.yaml"
_ARM_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000001/"
    "resourceGroups/rg-example/PROVIDERS/Microsoft.Storage/storageAccounts/example"
)


def _registry():
    return load_resource_type_registry_from_mapping(
        yaml.safe_load(_VOCABULARY.read_text(encoding="utf-8"))
    )


def _event(event_type: str) -> dict[str, object]:
    return {
        "id": "00000000-0000-0000-0000-000000000002",
        "eventType": event_type,
        "eventTime": "2026-07-18T01:02:03Z",
        "subject": _ARM_ID,
        "data": {
            "resourceUri": _ARM_ID,
            "operationName": "Microsoft.Storage/storageAccounts/write",
            "status": "Succeeded",
            "resourceProvider": "Microsoft.Storage",
        },
    }


@pytest.mark.parametrize(
    ("event_type", "change_kind"),
    [
        ("Microsoft.Resources.ResourceWriteSuccess", "upsert"),
        ("Microsoft.Resources.ResourceDeleteSuccess", "delete"),
    ],
)
def test_normalizes_resource_changes_with_contains_link(
    event_type: str,
    change_kind: str,
) -> None:
    (event,) = normalize_resource_change_events(
        [_event(event_type)],
        resource_types=_registry(),
        ingested_at=datetime(2026, 7, 18, 1, 2, 4, tzinfo=UTC),
    )

    change = event.payload["inventory_change"]
    assert change["kind"] == change_kind
    assert change["resource"]["type"] == "object-storage"
    assert change["resource"]["resource_id"] == event.resource_ref
    assert change["links"][0]["link_type"] == "contains"
    assert event.payload["signal_kind"] == "azure.activity_log"


def test_unsupported_event_type_is_ignored() -> None:
    assert (
        normalize_resource_change_events(
            [_event("Microsoft.Resources.ResourceActionSuccess")],
            resource_types=_registry(),
        )
        == ()
    )


def test_unknown_resource_type_fails_closed() -> None:
    unknown = _event("Microsoft.Resources.ResourceWriteSuccess")
    unknown_id = _ARM_ID.replace(
        "Microsoft.Storage/storageAccounts",
        "Microsoft.Unknown/widgets",
    )
    unknown["subject"] = unknown_id
    unknown["data"] = {"resourceUri": unknown_id, "status": "Succeeded"}
    with pytest.raises(ValueError, match="canonical vocabulary"):
        normalize_resource_change_events([unknown], resource_types=_registry())


def test_malformed_resource_change_fails_closed() -> None:
    malformed = _event("Microsoft.Resources.ResourceWriteSuccess")
    malformed["data"] = {"status": "Succeeded"}
    malformed["subject"] = ""
    with pytest.raises(ValueError, match="ARM resource id"):
        normalize_resource_change_events([malformed], resource_types=_registry())
