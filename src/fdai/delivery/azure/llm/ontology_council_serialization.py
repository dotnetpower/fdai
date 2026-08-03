"""Deterministic wire serialization for ontology council model requests."""

from __future__ import annotations

import json

from fdai.shared.providers.ontology_council import (
    CouncilClaimPacket,
    CouncilDispute,
)


def serialize_council_user_content(
    packet: CouncilClaimPacket,
    dispute: CouncilDispute | None = None,
) -> str:
    payload: dict[str, object] = {"packet": _packet_payload(packet)}
    if dispute is not None:
        payload["dispute"] = {
            "initial_vote_digests": list(dispute.initial_vote_digests),
            "differences": [
                {
                    "field_name": difference.field_name,
                    "value_digests": list(difference.value_digests),
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


__all__ = ["encode_council_request", "serialize_council_user_content"]
