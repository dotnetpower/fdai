"""Content-only identity for complete inventory reconciliation results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from fdai.delivery.inventory_sync_models import PromotedInventoryObservation
from fdai.shared.providers.state_evidence import (
    LINK_OBSERVATION_METADATA_PROPERTY,
    STATE_FACT_METADATA_PROPERTY,
)

_STATE_FACT_OBSERVATION_FIELDS = frozenset(
    {
        "effective_at",
        "evidence_cutoff",
        "evidence_refs",
        "recorded_at",
        "source_revision",
    }
)
_LINK_OBSERVATION_FIELDS = frozenset(
    {
        "inventory_generation",
        "verification_receipt_ref",
    }
)


def inventory_semantic_digest(observation: PromotedInventoryObservation) -> str:
    """Hash graph meaning and completeness without reconciliation-only clocks."""

    if not observation.complete:
        raise ValueError("inventory semantic digest requires a complete observation")
    resources = [
        {
            "id": item.resource_id,
            "type": item.type,
            "props": _resource_properties(item.props),
            "provider_ref": item.provider_ref,
        }
        for item in sorted(observation.resources, key=lambda item: item.resource_id)
    ]
    links = [
        {
            "from_id": item.from_id,
            "from_type": item.from_type,
            "link_type": item.link_type,
            "to_id": item.to_id,
            "to_type": item.to_type,
            "props": _link_properties(
                item.link_props,
                (
                    item.observation_metadata.to_mapping()
                    if item.observation_metadata is not None
                    else None
                ),
            ),
        }
        for item in sorted(
            observation.links,
            key=lambda item: (item.from_id, item.link_type, item.to_id),
        )
    ]
    drops = sorted(
        (
            item.reason.value,
            item.mapping_id,
            item.source_property_path,
            item.source_provider_type,
            item.target_provider_type,
            item.unavailable_reason.value if item.unavailable_reason is not None else None,
        )
        for item in observation.relationship_drops
    )
    body = {
        "resources": resources,
        "links": links,
        "relationship_drops": drops,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _resource_properties(value: Mapping[str, Any]) -> dict[str, Any]:
    properties = dict(value)
    raw = properties.get(STATE_FACT_METADATA_PROPERTY)
    if isinstance(raw, Mapping):
        properties[STATE_FACT_METADATA_PROPERTY] = _state_fact_collection(raw)
    return properties


def _link_properties(
    value: Mapping[str, Any],
    observation_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    properties = dict(value)
    if observation_metadata is not None:
        metadata = {
            key: item
            for key, item in observation_metadata.items()
            if key not in _LINK_OBSERVATION_FIELDS
        }
        raw_state_fact = metadata.get("state_fact")
        if isinstance(raw_state_fact, Mapping):
            metadata["state_fact"] = _state_fact(raw_state_fact)
        properties[LINK_OBSERVATION_METADATA_PROPERTY] = metadata
    return properties


def _state_fact_collection(value: Mapping[str, Any]) -> dict[str, Any]:
    if "lane" in value:
        return _state_fact(value)
    return {
        key: _state_fact(item) if isinstance(item, Mapping) else item for key, item in value.items()
    }


def _state_fact(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in _STATE_FACT_OBSERVATION_FIELDS}


__all__ = ["inventory_semantic_digest"]
