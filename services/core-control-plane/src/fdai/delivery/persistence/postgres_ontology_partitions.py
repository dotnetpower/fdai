"""Complete ordered storage partitions, distinct from provider shards and writer ownership."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.shared.providers.ontology_instance import OntologyInstanceValidationError


def partition_descriptor(chunk: str) -> dict[str, Any]:
    payload = json.loads(chunk)
    kind = payload.get("kind")
    records = payload.get("records")
    if (
        kind not in {"objects", "links"}
        or not isinstance(records, list)
        or not 1 <= len(records) <= 1000
    ):
        raise OntologyInstanceValidationError("ontology partition records are invalid")
    keys = [
        [record["id"]]
        if kind == "objects"
        else [record["from_id"], record["link_type"], record["to_id"]]
        for record in records
    ]
    if any(not isinstance(value, str) or not value for key in keys for value in key) or any(
        before >= after for before, after in zip(keys, keys[1:], strict=False)
    ):
        raise OntologyInstanceValidationError("ontology partition identity ordering is invalid")
    return {
        "digest": "sha256:" + hashlib.sha256(chunk.encode()).hexdigest(),
        "kind": kind,
        "count": len(keys),
        "first": keys[0],
        "last": keys[-1],
    }


def prepare_partition_set(chunks: Sequence[str]) -> dict[str, Any]:
    partitions = [partition_descriptor(chunk) for chunk in chunks]
    result = {
        "schema_version": "1.0.0",
        "ownership": "single-inventory-owner",
        "object_count": sum(part["count"] for part in partitions if part["kind"] == "objects"),
        "link_count": sum(part["count"] for part in partitions if part["kind"] == "links"),
        "partitions": partitions,
    }
    validate_partition_set(result, partitions)
    return result


def validate_partition_set(value: object, expected: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "ownership",
        "object_count",
        "link_count",
        "partitions",
    }:
        raise OntologyInstanceValidationError("ontology partition set is malformed")
    partitions = value["partitions"]
    if (
        value["schema_version"] != "1.0.0"
        or value["ownership"] != "single-inventory-owner"
        or not isinstance(partitions, list)
        or len(partitions) != len(expected)
        or len(partitions) > 1000
    ):
        raise OntologyInstanceValidationError("ontology partition set binding changed")
    prior: dict[str, list[str]] = {}
    saw_links = False
    counts = {"objects": 0, "links": 0}
    for part, bound in zip(partitions, expected, strict=True):
        if (
            not isinstance(part, dict)
            or set(part) != {"digest", "kind", "count", "first", "last"}
            or any(part.get(key) != bound.get(key) for key in ("digest", "kind", "count"))
        ):
            raise OntologyInstanceValidationError("ontology partition descriptor changed")
        kind = part["kind"]
        if kind not in counts or type(part["count"]) is not int or not 1 <= part["count"] <= 1000:
            raise OntologyInstanceValidationError("ontology partition count or kind is invalid")
        width = 1 if kind == "objects" else 3
        if any(
            not isinstance(part[key], list)
            or len(part[key]) != width
            or any(not isinstance(item, str) or not item for item in part[key])
            for key in ("first", "last")
        ):
            raise OntologyInstanceValidationError("ontology partition key range is malformed")
        if (
            part["first"] > part["last"]
            or (kind in prior and part["first"] <= prior[kind])
            or (saw_links and kind == "objects")
        ):
            raise OntologyInstanceValidationError("ontology partition ranges overlap or regress")
        prior[kind] = part["last"]
        saw_links = kind == "links"
        counts[kind] += part["count"]
    if any(
        type(value[field]) is not int or value[field] != counts[kind]
        for field, kind in (("object_count", "objects"), ("link_count", "links"))
    ):
        raise OntologyInstanceValidationError("ontology partition set is incomplete")
