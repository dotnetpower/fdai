"""Production operational-history archive writer and reader tests."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.archive_manifest import (
    ArchiveSourcePartition,
    build_archive_manifest,
)
from fdai.delivery.operational_history_archive import (
    OperationalArchiveArtifact,
    OperationalArchivePrincipal,
    OperationalHistoryArchiveReader,
    OperationalHistoryArchiveWriter,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
SOURCE = "sha256:" + "b" * 64
CREATION = "sha256:" + "c" * 64


class _Artifacts:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}

    async def put(self, storage_ref: str, content: bytes, *, digest: str) -> bool:
        assert hashlib.sha256(content).hexdigest() == digest
        prior = self.items.setdefault(storage_ref, content)
        if prior != content:
            raise ValueError("artifact collision")
        return prior is content

    async def get(self, storage_ref: str) -> bytes | None:
        return self.items.get(storage_ref)


class _Metadata:
    def __init__(self) -> None:
        self.item: OperationalArchiveArtifact | None = None

    async def put_archive_artifact(self, artifact: OperationalArchiveArtifact) -> bool:
        if self.item is not None and self.item != artifact:
            raise ValueError("metadata collision")
        created = self.item is None
        self.item = artifact
        return created

    async def get_archive_artifact(
        self,
        manifest_digest: str,
    ) -> OperationalArchiveArtifact | None:
        if self.item is None or self.item.manifest_digest != manifest_digest:
            return None
        return self.item

    async def is_archive_verified(self, manifest_digest: str) -> bool:
        return self.item is not None and self.item.manifest_digest == manifest_digest


class _Manifests:
    def __init__(self) -> None:
        self.digest: str | None = None

    async def put_manifest(self, manifest) -> bool:
        created = self.digest is None
        if self.digest not in {None, manifest.digest}:
            raise ValueError("manifest collision")
        self.digest = manifest.digest
        return created


def _fixture():
    records = ({"observation_id": SOURCE, "properties": {"status": "running"}},)
    encoded = (
        json.dumps(
            {
                "schema_version": "1.0.0",
                "source_partition_digests": [SOURCE],
                "records": list(records),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    partition = ArchiveSourcePartition(
        partition_id="partition-1",
        content_digest=SOURCE,
        interval_start=NOW,
        interval_end=NOW + timedelta(hours=1),
        object_count=1,
        relationship_count=0,
        schema_version="inventory-observation-1.0.0",
        ontology_release_digest=RELEASE,
        complete=True,
    )
    manifest = build_archive_manifest(
        (partition,),
        archive_content_digest="sha256:" + hashlib.sha256(encoded).hexdigest(),
        compression_profile="none",
        encryption_profile="platform-managed",
        destination_class="private-blob",
        retention_class="operational-history",
        creation_receipt_digest=CREATION,
        created_at=NOW + timedelta(hours=2),
    )
    return manifest, records


async def test_writer_and_principal_scoped_reader_preserve_exact_artifact() -> None:
    manifest, records = _fixture()
    artifacts = _Artifacts()
    metadata = _Metadata()
    writer = OperationalHistoryArchiveWriter(
        artifacts=artifacts,
        metadata=metadata,
        manifests=_Manifests(),
    )
    reader = OperationalHistoryArchiveReader(
        artifacts=artifacts,
        metadata=metadata,
    )

    artifact = await writer.write(
        manifest,
        records,
        scope_refs=("scope-example",),
        allowed_purposes=("incident-investigation",),
    )
    read = await reader.read(
        principal=OperationalArchivePrincipal(
            principal_id="principal-example",
            purpose="incident-investigation",
            scope_refs=("scope-example",),
        ),
        manifest_digest=manifest.digest,
    )

    assert read.artifact_digest == artifact.artifact_digest
    assert json.loads(read.content)["records"] == list(records)
    assert read.execution_authority is False


async def test_reader_fails_closed_on_purpose_scope_or_content_mismatch() -> None:
    manifest, records = _fixture()
    artifacts = _Artifacts()
    metadata = _Metadata()
    writer = OperationalHistoryArchiveWriter(
        artifacts=artifacts,
        metadata=metadata,
        manifests=_Manifests(),
    )
    reader = OperationalHistoryArchiveReader(
        artifacts=artifacts,
        metadata=metadata,
    )
    artifact = await writer.write(
        manifest,
        records,
        scope_refs=("scope-example",),
        allowed_purposes=("incident-investigation",),
    )

    with pytest.raises(PermissionError, match="purpose"):
        await reader.read(
            principal=OperationalArchivePrincipal(
                principal_id="principal-example",
                purpose="disaster-recovery",
                scope_refs=("scope-example",),
            ),
            manifest_digest=manifest.digest,
        )
    with pytest.raises(PermissionError, match="scope"):
        await reader.read(
            principal=OperationalArchivePrincipal(
                principal_id="principal-example",
                purpose="incident-investigation",
                scope_refs=("scope-other",),
            ),
            manifest_digest=manifest.digest,
        )
    artifacts.items[artifact.storage_ref] += b"tamper"
    with pytest.raises(ValueError, match="byte count changed"):
        await reader.read(
            principal=OperationalArchivePrincipal(
                principal_id="principal-example",
                purpose="incident-investigation",
                scope_refs=("scope-example",),
            ),
            manifest_digest=manifest.digest,
        )
