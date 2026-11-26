"""Export the complete stored ontology map and pseudonymized local DB instances, read-only."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from local_ontology_db import ROOT, connect_readonly, local_connection_parameters

MAX_INSTANCES = 25_000
MAX_LINKS = 100_000
MAX_HISTORY = 50_000
SAFE_STATES = frozenset(
    {
        "running",
        "ready",
        "succeeded",
        "available",
        "online",
        "active",
        "enabled",
        "failed",
        "degraded",
        "unavailable",
        "stopped",
        "stopping",
        "deallocated",
        "disabled",
        "paused",
        "pending",
        "unknown",
        "notready",
        "not ready",
        "provisioning",
        "updating",
        "creating",
        "deleting",
        "deleted",
        "closed",
        "open",
        "completed",
        "in_progress",
        "rejected",
        "approved",
        "cancelled",
        "canceled",
        "attached",
        "unattached",
        "connected",
        "collecting",
    }
)


def safe_state(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip().lower() in SAFE_STATES else None


def iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return iso(parsed) if parsed.tzinfo else None


def export_database_map() -> dict[str, Any]:
    """Export all bounded rows with exact counts; refuse rather than silently sample."""
    parameters = local_connection_parameters(ROOT / ".fdai/local-runtime.env")
    credential = parameters.get("password")
    if not isinstance(credential, str) or not credential:
        raise ValueError("A service credential is required for private identity pseudonyms.")
    key = hashlib.sha256(("fdai-neural-view-v1:" + credential).encode()).digest()

    def opaque(value: str, prefix: str = "db") -> str:
        return f"{prefix}:" + hmac.new(key, value.encode(), hashlib.sha256).hexdigest()[:24]

    with connect_readonly() as connection:
        captured_at = iso(
            connection.execute("SELECT transaction_timestamp() AS time").fetchone()["time"]
        )
        row = connection.execute(
            "SELECT value FROM state_kv WHERE key = %s",
            ("operator-projection:operations:ontology.graph",),
        ).fetchone()
        if row is None:
            raise ValueError("The stored Console ontology map is unavailable.")
        projection = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
        catalog = projection.get("catalog_topology")
        if not isinstance(catalog, dict) or catalog.get("mutationAuthority") is not False:
            raise ValueError("The stored ontology map has no valid read-only topology.")
        declarations = connection.execute(
            "SELECT name, version FROM ontology_object_type ORDER BY name"
        ).fetchall()
        counts = connection.execute(
            "SELECT object_type, count(*) AS count FROM ontology_resource "
            "GROUP BY object_type ORDER BY object_type"
        ).fetchall()
        instance_counts = {row["object_type"]: row["count"] for row in counts}
        instance_total = sum(instance_counts.values())
        link_total = connection.execute("SELECT count(*) AS count FROM ontology_link").fetchone()[
            "count"
        ]
        history_total = connection.execute(
            "SELECT count(*) AS count FROM operational_state_transition"
        ).fetchone()["count"]
        if instance_total > MAX_INSTANCES or link_total > MAX_LINKS or history_total > MAX_HISTORY:
            raise ValueError(
                "The local graph exceeds the explicit export budget; no subset was exported."
            )
        instance_rows = connection.execute(
            "WITH scoped AS ("
            " SELECT id, object_type, revision, type_version, catalog_digest, "
            " properties->>'type' AS resource_type, "
            " COALESCE(properties#>>'{properties,state}', properties->>'state', "
            " properties->>'status') AS state, "
            " COALESCE(properties#>'{properties,state_fact_metadata,state}', "
            " properties#>'{properties,state_fact_metadata}') AS metadata "
            " FROM ontology_resource"
            ") SELECT id, object_type, revision, type_version, catalog_digest, resource_type, "
            " state, metadata->>'lane' AS lane, metadata->>'authority' AS authority, "
            " metadata->>'effective_at' AS effective_at, metadata->>'recorded_at' AS recorded_at, "
            " metadata->>'evidence_cutoff' AS evidence_cutoff, "
            " metadata->'synthetic' AS synthetic "
            " FROM scoped ORDER BY object_type, id"
        ).fetchall()
        link_rows = connection.execute(
            "SELECT from_id, to_id, link_type, type_version, catalog_digest "
            "FROM ontology_link ORDER BY from_id, link_type, to_id"
        ).fetchall()
        history_rows = connection.execute(
            "SELECT transition_id, subject_ref, subject_type, state_type, from_state, to_state, "
            "lane, authority, effective_at, recorded_at, evidence_cutoff, synthetic, "
            "completeness_basis_points, cardinality(conflicts) AS conflicts "
            "FROM operational_state_transition ORDER BY effective_at, recorded_at, transition_id"
        ).fetchall()
        coverage = connection.execute(
            "SELECT limitation, complete, count(*) AS count "
            "FROM operational_state_transition_coverage GROUP BY limitation, complete "
            "ORDER BY limitation, complete"
        ).fetchall()

    catalog_nodes = []
    for node in catalog["nodes"]:
        catalog_nodes.append(
            {
                "id": f"catalog:{node['id']}",
                "label": node["label"],
                "kind": node["kind"],
                "objectType": node["label"] if node["kind"] == "object_type" else None,
                "group": node["group"],
                "detail": node["detail"],
                "x": node["x"],
                "y": node["y"],
                "community": node["community"],
                "degree": node["degree"],
                "instanceCount": instance_counts.get(node["label"], 0)
                if node["kind"] == "object_type"
                else None,
            }
        )
    type_nodes = {
        node["objectType"]: node["id"] for node in catalog_nodes if node["kind"] == "object_type"
    }
    missing_types = {row["name"] for row in declarations} - set(type_nodes)
    if missing_types or set(instance_counts) - set(type_nodes):
        raise ValueError(
            "The stored map is missing database ObjectTypes; refresh the authoritative map."
        )
    catalog_edges = [
        {
            "id": f"catalog:{edge['id']}",
            "source": f"catalog:{edge['source']}",
            "target": f"catalog:{edge['target']}",
            "type": edge["label"],
            "kind": edge["kind"],
            "origin": "catalog",
        }
        for edge in catalog["edges"]
    ]
    instances = []
    original_ids = set()
    for row in instance_rows:
        identifier = opaque(row["id"])
        original_ids.add(row["id"])
        object_type = row["object_type"]
        resource_type = row["resource_type"]
        # Only reviewed public ResourceType identifiers may qualify a private instance label.
        allowed_resource_type = (
            resource_type
            if (
                isinstance(resource_type, str)
                and any(node["id"] == f"catalog:rt:{resource_type}" for node in catalog_nodes)
            )
            else None
        )
        state = safe_state(row["state"])
        instances.append(
            {
                "id": identifier,
                "label": f"{allowed_resource_type or object_type} / {identifier[-6:]}",
                "kind": "instance",
                "objectType": object_type,
                "resourceType": allowed_resource_type,
                "typeNode": type_nodes[object_type],
                "revision": row["revision"],
                "typeVersion": row["type_version"],
                "catalogDigest": row["catalog_digest"],
                "state": {
                    "value": state,
                    "lane": row["lane"]
                    if row["lane"] in {"observed", "derived", "desired", "execution"}
                    else "stored",
                    "authority": row["authority"]
                    if row["authority"] in {"provider", "telemetry", "deterministic_function"}
                    else None,
                    "effectiveAt": iso(row["effective_at"]),
                    "recordedAt": iso(row["recorded_at"]),
                    "evidenceCutoff": iso(row["evidence_cutoff"]),
                    "synthetic": row["synthetic"],
                },
            }
        )
    if len({node["id"] for node in instances}) != instance_total:
        raise ValueError("Pseudonymized instance identities are not unique.")
    db_edges = []
    unresolved_links = 0
    for index, row in enumerate(link_rows):
        if row["from_id"] not in original_ids or row["to_id"] not in original_ids:
            unresolved_links += 1
            continue
        db_edges.append(
            {
                "id": f"db-link:{index}",
                "source": opaque(row["from_id"]),
                "target": opaque(row["to_id"]),
                "type": row["link_type"],
                "kind": "instance_link",
                "origin": "database",
            }
        )
    membership = [
        {
            "id": f"classification:{node['id']}",
            "source": node["id"],
            "target": node["typeNode"],
            "type": "instance_of",
            "kind": "classification",
            "origin": "classification",
        }
        for node in instances
    ]
    history = [
        {
            "id": opaque(row["transition_id"], "transition"),
            "subject": opaque(row["subject_ref"]),
            "objectType": row["subject_type"],
            "stateType": row["state_type"],
            "before": safe_state(row["from_state"]),
            "after": safe_state(row["to_state"]),
            "lane": row["lane"],
            "authority": row["authority"],
            "effectiveAt": iso(row["effective_at"]),
            "recordedAt": iso(row["recorded_at"]),
            "evidenceCutoff": iso(row["evidence_cutoff"]),
            "synthetic": row["synthetic"],
            "completeness": row["completeness_basis_points"] / 10000,
            "conflicts": row["conflicts"],
            "currentInstance": row["subject_ref"] in original_ids,
        }
        for row in history_rows
    ]
    return {
        "version": 2,
        "source": {
            "kind": "local-postgresql",
            "capturedAt": captured_at,
            "readOnly": True,
            "isolation": "repeatable-read",
            "privacy": "pseudonymized-identities-no-bodies",
            "catalogDigest": catalog["ontologyReleaseDigest"],
            "catalogComplete": projection.get("complete") is True,
            "databaseReadComplete": True,
        },
        "counts": {
            "objectTypes": len(declarations),
            "catalogNodes": len(catalog_nodes),
            "catalogLinks": len(catalog_edges),
            "instances": instance_total,
            "storedLinks": link_total,
            "resolvedStoredLinks": len(db_edges),
            "unresolvedStoredLinks": unresolved_links,
            "history": history_total,
            "historyForCurrentInstances": sum(item["currentInstance"] for item in history),
            "byType": instance_counts,
        },
        "nodes": [*catalog_nodes, *instances],
        "links": [*catalog_edges, *db_edges, *membership],
        "history": history,
        "historyCoverage": coverage,
    }


def write_private_snapshot(snapshot: dict[str, Any], directory: Path | None = None) -> Path:
    directory = directory or ROOT / ".fdai/neural-view"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    destination = directory / "ontology.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory, delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump(snapshot, file, ensure_ascii=False, separators=(",", ":"))
            file.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return destination


if __name__ == "__main__":
    try:
        data = export_database_map()
        destination = write_private_snapshot(data)
        print(json.dumps({"source": data["source"]["kind"], "read_only": True, **data["counts"]}))
        print(
            "Private snapshot updated; raw IDs, names, credentials "
            "and content bodies were not exported."
        )
    except (psycopg.Error, OSError, ValueError, KeyError) as error:
        raise SystemExit(
            f"Local ontology export failed: {type(error).__name__}. "
            "No sample data was substituted; connection and row values are withheld."
        ) from None
