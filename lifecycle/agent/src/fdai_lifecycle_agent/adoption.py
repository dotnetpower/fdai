"""Interruptible per-object adoption of Terraform-owned runtime objects."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from fdai_deployment_cli.contracts import canonical_digest

from fdai_lifecycle_agent.state import write_json_atomically
from fdai_lifecycle_agent.workload import Manifest, WorkloadError, object_key

ADOPTION_SCHEMA = "fdai.runtime-adoption-receipt.v1"
ADOPTION_RELEASE_SCHEMA = "fdai.runtime-adoption-release.v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)
_MAX_RECEIPT_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class AdoptionExpectation:
    kind: str
    name: str
    uid: str
    resource_version: str
    source_digest: str | None = None

    def __post_init__(self) -> None:
        if any(
            _ID.fullmatch(value) is None
            for value in (self.kind, self.name, self.uid, self.resource_version)
        ) or (
            self.source_digest is not None
            and re.fullmatch(r"sha256:[0-9a-f]{64}", self.source_digest) is None
        ):
            raise ValueError("adoption expectation is invalid")

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.name


class AdoptionCluster(Protocol):
    def get(self, kind: str, name: str) -> Manifest | None: ...

    def adopt_terraform_owned(
        self,
        manifest: Manifest,
        *,
        uid: str,
        resource_version: str,
    ) -> Manifest: ...


def adopt_runtime_objects(
    cluster: AdoptionCluster,
    manifests: Sequence[Manifest],
    expectations: Sequence[AdoptionExpectation],
    *,
    installation_id: str,
    release_id: str,
    destination: Path,
    authorization_digest: str | None = None,
    ownership_digest: str | None = None,
) -> dict[str, object]:
    """Adopt exact live objects and durably checkpoint each successful transfer."""

    if _ID.fullmatch(installation_id) is None or _ID.fullmatch(release_id) is None:
        raise ValueError("adoption identity is invalid")
    for digest in (authorization_digest, ownership_digest):
        if digest is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise ValueError("adoption authorization digest is invalid")
    desired = {object_key(manifest): manifest for manifest in manifests}
    expected = {item.key: item for item in expectations}
    if len(desired) != len(manifests) or len(expected) != len(expectations):
        raise ValueError("adoption objects must be unique")
    if set(desired) != set(expected):
        raise ValueError("adoption expectations must exactly match rendered objects")
    retained = _load(
        destination,
        installation_id=installation_id,
        release_id=release_id,
        authorization_digest=authorization_digest,
        ownership_digest=ownership_digest,
    )
    retained_objects = cast(list[dict[str, object]], retained["objects"])
    records = {(str(item["kind"]), str(item["name"])): item for item in retained_objects}
    for key in sorted(desired):
        manifest = desired[key]
        expectation = expected[key]
        render_digest = "sha256:" + canonical_digest(manifest)
        if key in records:
            _verify_retained(records[key], expectation, render_digest)
            live = cluster.get(*key)
            metadata = (live or {}).get("metadata", {})
            if metadata.get("uid") != expectation.uid:
                raise WorkloadError("adoption_resource_identity_changed")
            retained_source = records[key].get("source_digest")
            if isinstance(retained_source, str):
                unchanged = live is not None and adoption_source_digest(live) == retained_source
            else:
                unchanged = (
                    metadata.get("resourceVersion") == records[key]["resource_version"]
                    or metadata.get("annotations", {}).get("fdai.io/adopted-from") == "Terraform"
                )
            if not unchanged:
                raise WorkloadError("adoption_resource_drifted")
            continue
        live = cluster.get(*key)
        metadata = (live or {}).get("metadata", {})
        version = metadata.get("resourceVersion")
        if live is None or not isinstance(version, str):
            raise WorkloadError("adoption_object_unknown")
        if metadata.get("uid") != expectation.uid or (
            version != expectation.resource_version
            and (
                expectation.source_digest is None
                or adoption_source_digest(live) != expectation.source_digest
            )
        ):
            raise WorkloadError("adoption_resource_drifted")
        adopted = cluster.adopt_terraform_owned(
            manifest,
            uid=expectation.uid,
            resource_version=version,
        )
        adopted_metadata = adopted.get("metadata", {})
        if adopted_metadata.get("uid") != expectation.uid or not isinstance(
            adopted_metadata.get("resourceVersion"), str
        ):
            raise WorkloadError("adoption_receipt_invalid")
        records[key] = {
            "kind": key[0],
            "name": key[1],
            "uid": expectation.uid,
            "resource_version": adopted_metadata["resourceVersion"],
            "render_digest": render_digest,
            "source_digest": adoption_source_digest(adopted),
        }
        _write(
            destination,
            installation_id=installation_id,
            release_id=release_id,
            records=records,
            complete=False,
            authorization_digest=authorization_digest,
            ownership_digest=ownership_digest,
        )
    return _write(
        destination,
        installation_id=installation_id,
        release_id=release_id,
        records=records,
        complete=True,
        authorization_digest=authorization_digest,
        ownership_digest=ownership_digest,
    )


def release_adoption_reconciliation(
    adoption_receipt: Path,
    *,
    destination: Path,
) -> dict[str, object]:
    """Record that the Agent stopped reconciling before Terraform rollback import."""

    try:
        parsed = json.loads(adoption_receipt.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError
        receipt = cast(dict[str, object], parsed)
        receipt_digest = receipt.get("receipt_digest")
        body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
        if (
            body.get("schema_version") != ADOPTION_SCHEMA
            or body.get("complete") is not True
            or not isinstance(receipt_digest, str)
            or receipt_digest != "sha256:" + canonical_digest(body)
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise WorkloadError("adoption_release_receipt_invalid") from None
    release: dict[str, object] = {
        "schema_version": ADOPTION_RELEASE_SCHEMA,
        "installation_id": body["installation_id"],
        "release_id": body["release_id"],
        "adoption_receipt_digest": receipt_digest,
        "reconciliation_released": True,
    }
    document = release | {"receipt_digest": "sha256:" + canonical_digest(release)}
    write_json_atomically(destination, document)
    return document


def adoption_source_digest(manifest: Manifest) -> str:
    metadata = manifest.get("metadata", {})
    return "sha256:" + canonical_digest(
        {
            "apiVersion": manifest.get("apiVersion"),
            "kind": manifest.get("kind"),
            "metadata": {
                key: metadata.get(key)
                for key in ("name", "namespace", "labels", "annotations", "ownerReferences")
                if metadata.get(key) is not None
            },
            "spec": manifest.get("spec"),
        }
    )


def _load(
    destination: Path,
    *,
    installation_id: str,
    release_id: str,
    authorization_digest: str | None,
    ownership_digest: str | None,
) -> dict[str, object]:
    if not destination.exists():
        return {"objects": []}
    try:
        if destination.is_symlink() or destination.stat().st_size > _MAX_RECEIPT_BYTES:
            raise ValueError
        parsed = json.loads(destination.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError
        document = cast(dict[str, object], parsed)
        digest = document.pop("receipt_digest", None)
        objects = document.get("objects")
        if (
            document.get("schema_version") != ADOPTION_SCHEMA
            or document.get("installation_id") != installation_id
            or document.get("release_id") != release_id
            or document.get("authorization_digest") != authorization_digest
            or document.get("ownership_digest") != ownership_digest
            or not isinstance(objects, list)
            or not all(isinstance(item, dict) for item in objects)
            or not isinstance(document.get("complete"), bool)
            or digest != "sha256:" + canonical_digest(document)
        ):
            raise ValueError
        return document
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        raise WorkloadError("adoption_receipt_unreadable") from None


def _write(
    destination: Path,
    *,
    installation_id: str,
    release_id: str,
    records: Mapping[tuple[str, str], Mapping[str, object]],
    complete: bool,
    authorization_digest: str | None,
    ownership_digest: str | None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": ADOPTION_SCHEMA,
        "installation_id": installation_id,
        "release_id": release_id,
        "objects": [dict(records[key]) for key in sorted(records)],
        "complete": complete,
    }
    if authorization_digest is not None:
        body["authorization_digest"] = authorization_digest
    if ownership_digest is not None:
        body["ownership_digest"] = ownership_digest
    receipt = body | {"receipt_digest": "sha256:" + canonical_digest(body)}
    write_json_atomically(destination, receipt)
    return receipt


def _verify_retained(
    record: Mapping[str, object],
    expectation: AdoptionExpectation,
    render_digest: str,
) -> None:
    if (
        record.get("kind") != expectation.kind
        or record.get("name") != expectation.name
        or record.get("uid") != expectation.uid
        or record.get("render_digest") != render_digest
        or not isinstance(record.get("resource_version"), str)
    ):
        raise WorkloadError("adoption_receipt_conflict")
