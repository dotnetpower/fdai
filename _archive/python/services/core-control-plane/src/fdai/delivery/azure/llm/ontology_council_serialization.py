"""Deterministic wire serialization for ontology council model requests."""

from __future__ import annotations

import json

from fdai.shared.providers.ontology_council import (
    CouncilClaimPacket,
    CouncilDispute,
)


def ontology_council_vote_schema() -> dict[str, object]:
    """Return the strict fixed-field schema accepted by Azure structured output."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "claim_id",
            "citation_digest",
            "disposition",
            "operation",
            "target_kind",
            "target_type",
            "target_identity",
            "authority",
            "properties",
            "from_identity",
            "to_identity",
            "semantics",
        ],
        "properties": {
            "claim_id": {"type": "string"},
            "citation_digest": {"type": "string"},
            "disposition": {
                "type": "string",
                "enum": ["propose", "unsupported", "abstain"],
            },
            "operation": {
                "type": ["string", "null"],
                "enum": ["add", "update", "remove", "supersede", None],
            },
            "target_kind": {
                "type": ["string", "null"],
                "enum": ["object", "link", None],
            },
            "target_type": {"type": ["string", "null"]},
            "target_identity": {"type": ["string", "null"]},
            "authority": {"type": ["string", "null"]},
            "properties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "value"],
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": ["string", "number", "boolean", "null"]},
                    },
                },
            },
            "from_identity": {"type": ["string", "null"]},
            "to_identity": {"type": ["string", "null"]},
            "semantics": {
                "anyOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "numbers",
                            "units",
                            "comparators",
                            "negated",
                            "effective_from",
                            "effective_to",
                        ],
                        "properties": {
                            "numbers": {"type": "array", "items": {"type": "string"}},
                            "units": {"type": "array", "items": {"type": "string"}},
                            "comparators": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "negated": {"type": "boolean"},
                            "effective_from": {"type": ["string", "null"]},
                            "effective_to": {"type": ["string", "null"]},
                        },
                    },
                    {"type": "null"},
                ]
            },
        },
    }


def serialize_council_user_content(
    packet: CouncilClaimPacket,
    dispute: CouncilDispute | None = None,
) -> str:
    payload: dict[str, object] = {"packet": _packet_payload(packet)}
    if dispute is not None:
        payload["dispute"] = {
            "initial_vote_digests": list(dispute.initial_vote_digests),
            "agreed_fields": [
                {
                    "field_name": field.field_name,
                    "digest": field.alternative.digest,
                    "value": json.loads(field.alternative.value_json),
                }
                for field in dispute.agreed_fields
            ],
            "differences": [
                {
                    "field_name": difference.field_name,
                    "value_digests": list(difference.value_digests),
                    "alternatives": [
                        {
                            "digest": alternative.digest,
                            "value": json.loads(alternative.value_json),
                        }
                        for alternative in difference.alternatives
                    ],
                }
                for difference in dispute.differences
            ],
        }
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def encode_council_request(body: dict[str, object]) -> bytes:
    return json.dumps(
        body,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _packet_payload(packet: CouncilClaimPacket) -> dict[str, object]:
    return {
        "claim_id": packet.claim_id,
        "source_assertion": packet.source_assertion,
        "source_ref": packet.source_ref,
        "source_lines": list(packet.source_lines),
        "content_sha256": packet.content_sha256,
        "citation_digest": packet.citation_digest,
        "authority": packet.authority,
        "ontology_release": packet.ontology_release,
        "graph_revision": packet.graph_revision,
        "object_types": [
            {"name": item.name, "properties": list(item.properties)} for item in packet.object_types
        ],
        "links": [
            {
                "name": item.name,
                "from_type": item.from_type,
                "to_type": item.to_type,
                "properties": list(item.properties),
            }
            for item in packet.links
        ],
        "entities": [
            {"identity": item.identity, "object_type": item.object_type} for item in packet.entities
        ],
        "aliases": [{"alias": item.alias, "identity": item.identity} for item in packet.aliases],
    }


__all__ = [
    "encode_council_request",
    "ontology_council_vote_schema",
    "serialize_council_user_content",
]
