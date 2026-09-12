"""Protected exact-revision Cost Governance lifecycle command."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from pathlib import Path, PurePosixPath

import psycopg
from fdai.delivery.persistence.postgres_cost_governance_validation import (
    PostgresCostGovernanceValidationStore,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_MAX_JSON_BYTES = 1024 * 1024
_MAX_WHEEL_BYTES = 256 * 1024 * 1024
_MAX_WHEEL_CONTENT_BYTES = 512 * 1024 * 1024
_PACKAGE_ID = "cost-governance"
_VERTICAL_ID = "cost-governance"
_RESOURCE_ROOT = PurePosixPath("fdai_cost_governance/resources")


@dataclass(frozen=True, slots=True)
class _ReleaseIdentity:
    package_version: str
    wheel_digest: str
    asset_manifest_digest: str
    semantic_profile_digest: str
    ontology_release_digest: str


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("install", "enable", "disable", "upgrade", "rollback"),
    )
    parser.add_argument("--expected-revision", type=int, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--actor-id")
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--image-digest")
    parser.add_argument("--source-revision")
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument("--ontology-release-id")
    parser.add_argument("--evidence-ref", action="append", default=[])
    return parser


async def _run(args: argparse.Namespace, env: Mapping[str, str]) -> dict[str, object]:
    dsn = env.get("FDAI_STATE_STORE_DSN", "").strip()
    if not dsn:
        raise ValueError("FDAI_STATE_STORE_DSN MUST be configured")
    if args.expected_revision < 0:
        raise ValueError("expected revision MUST be nonnegative")

    if args.operation in {"enable", "disable"}:
        if not args.actor_id:
            raise ValueError("enable and disable require --actor-id")
        activation, replayed = await _set_enabled(
            dsn=dsn,
            enabled=args.operation == "enable",
            expected_revision=args.expected_revision,
            request_id=args.request_id,
            actor_id=args.actor_id,
        )
    else:
        identity = _release_identity(_required_path(args.wheel, "--wheel"))
        image_digest = _required_digest(args.image_digest, "--image-digest")
        source_revision = _required_revision(args.source_revision)
        runtime_config_digest = _runtime_config_digest(
            _required_path(args.runtime_config, "--runtime-config")
        )
        ontology_release_id = _required_text(
            args.ontology_release_id,
            "--ontology-release-id",
        )
        evidence_refs = tuple(dict.fromkeys(args.evidence_ref))
        if not evidence_refs:
            raise ValueError("release registration requires --evidence-ref")
        activation, replayed = await _register_release(
            dsn=dsn,
            operation=args.operation,
            expected_revision=args.expected_revision,
            request_id=args.request_id,
            evidence_refs=evidence_refs,
            identity=identity,
            image_digest=image_digest,
            source_revision=source_revision,
            runtime_config_digest=runtime_config_digest,
            ontology_release_id=ontology_release_id,
        )

    receipts = await PostgresCostGovernanceValidationStore(
        dsn=dsn
    ).read_cost_lifecycle_receipts(_PACKAGE_ID, limit=10_000)
    receipt = next(
        (item for item in receipts if item.idempotency_key == args.request_id),
        None,
    )
    if receipt is None or receipt.operation.value != args.operation:
        raise RuntimeError("Cost Governance lifecycle receipt verification failed")
    return {
        "activation_revision": receipt.revision_pin.activation_revision,
        "available": receipt.available,
        "current_activation_revision": activation["revision"],
        "current_enabled": activation["enabled"],
        "enabled": receipt.enabled,
        "evidence_kind": receipt.evidence_kind.value,
        "operation": receipt.operation.value,
        "package_id": receipt.revision_pin.package_id,
        "receipt_digest": receipt.digest,
        "receipt_id": receipt.receipt_id,
        "replayed": replayed,
        "revision_pin_digest": receipt.revision_pin.digest,
        "source_revision": receipt.revision_pin.source_revision,
    }


async def _register_release(
    *,
    dsn: str,
    operation: str,
    expected_revision: int,
    request_id: str,
    evidence_refs: tuple[str, ...],
    identity: _ReleaseIdentity,
    image_digest: str,
    source_revision: str,
    runtime_config_digest: str,
    ontology_release_id: str,
) -> tuple[dict[str, object], bool]:
    async with await psycopg.AsyncConnection.connect(
        _psycopg_dsn(dsn),
        row_factory=dict_row,
        connect_timeout=10,
    ) as connection:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"cost-governance-release:{_PACKAGE_ID}",),
        )
        replay_cursor = await connection.execute(
            """
            SELECT 1
              FROM cost_governance_lifecycle_receipt
             WHERE idempotency_key = %s
            """,
            (request_id,),
        )
        replayed = await replay_cursor.fetchone() is not None
        cursor = await connection.execute(
            """
            SELECT * FROM fdai_register_cost_governance_release(
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                operation,
                _PACKAGE_ID,
                _VERTICAL_ID,
                identity.package_version,
                image_digest,
                identity.wheel_digest,
                identity.asset_manifest_digest,
                identity.semantic_profile_digest,
                ontology_release_id,
                identity.ontology_release_digest,
                source_revision,
                runtime_config_digest,
                expected_revision,
                request_id,
                Jsonb(list(evidence_refs)),
            ),
        )
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Cost Governance release registration returned no state")
    return dict(row), replayed


async def _set_enabled(
    *,
    dsn: str,
    enabled: bool,
    expected_revision: int,
    request_id: str,
    actor_id: str,
) -> tuple[dict[str, object], bool]:
    async with await psycopg.AsyncConnection.connect(
        _psycopg_dsn(dsn),
        row_factory=dict_row,
        connect_timeout=10,
    ) as connection:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"cost-governance-settings:{_PACKAGE_ID}",),
        )
        replay_cursor = await connection.execute(
            """
            SELECT 1
              FROM cost_governance_lifecycle_receipt
             WHERE idempotency_key = %s
            """,
            (request_id,),
        )
        replayed = await replay_cursor.fetchone() is not None
        cursor = await connection.execute(
            "SELECT * FROM fdai_set_cost_governance_enabled(%s, %s, %s, %s, %s)",
            (_PACKAGE_ID, actor_id, enabled, expected_revision, request_id),
        )
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("Cost Governance activation returned no state")
    return dict(row), replayed


def _release_identity(path: Path) -> _ReleaseIdentity:
    if not path.is_file() or path.stat().st_size > _MAX_WHEEL_BYTES:
        raise ValueError("--wheel MUST be a bounded regular file")
    wheel_bytes = path.read_bytes()
    wheel_digest = f"sha256:{hashlib.sha256(wheel_bytes).hexdigest()}"
    with zipfile.ZipFile(path) as archive:
        names = tuple(archive.namelist())
        if len(names) != len(set(names)):
            raise ValueError("wheel MUST NOT contain duplicate member names")
        if sum(item.file_size for item in archive.infolist()) > _MAX_WHEEL_CONTENT_BYTES:
            raise ValueError("wheel uncompressed content exceeds the byte limit")
        if any(
            PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            for name in names
        ):
            raise ValueError("wheel member path escapes the package archive")
        metadata_names = tuple(
            name
            for name in names
            if name.startswith("fdai_cost_governance-") and name.endswith(".dist-info/METADATA")
        )
        if len(metadata_names) != 1:
            raise ValueError("wheel MUST contain one Cost Governance METADATA file")
        metadata = BytesParser(policy=default).parsebytes(archive.read(metadata_names[0]))
        if metadata.get("Name") != "fdai-cost-governance":
            raise ValueError("wheel package identity is not fdai-cost-governance")
        package_version = str(metadata.get("Version", ""))
        if re.fullmatch(r"[0-9]+[.][0-9]+[.][0-9]+", package_version) is None:
            raise ValueError("wheel package version MUST use MAJOR.MINOR.PATCH")
        manifest = _json_object(
            archive.read(str(_RESOURCE_ROOT / "manifest.json")),
            label="wheel resource manifest",
        )
        if (
            manifest.get("package_id") != _PACKAGE_ID
            or manifest.get("package_version") != package_version
            or manifest.get("candidate_state") != "inert"
        ):
            raise ValueError("wheel resource manifest identity is inconsistent")
        assets = manifest.get("assets")
        if not isinstance(assets, list) or not assets:
            raise ValueError("wheel resource manifest assets MUST be non-empty")
        asset_ids: set[str] = set()
        asset_paths: set[str] = set()
        asset_digests: set[str] = set()
        for asset in assets:
            if not isinstance(asset, dict):
                raise ValueError("wheel resource manifest asset is invalid")
            relative_path = asset.get("path")
            expected_digest = asset.get("sha256")
            if not isinstance(relative_path, str) or not isinstance(expected_digest, str):
                raise ValueError("wheel resource manifest asset identity is invalid")
            asset_id = asset.get("id")
            resource_path = PurePosixPath(relative_path)
            if (
                not isinstance(asset_id, str)
                or not asset_id
                or resource_path.is_absolute()
                or ".." in resource_path.parts
                or asset_id in asset_ids
                or relative_path in asset_paths
                or expected_digest in asset_digests
            ):
                raise ValueError("wheel resource manifest assets MUST be unique and bounded")
            resource = archive.read(str(_RESOURCE_ROOT / resource_path))
            if hashlib.sha256(resource).hexdigest() != expected_digest:
                raise ValueError("wheel package resource digest mismatch")
            asset_ids.add(asset_id)
            asset_paths.add(relative_path)
            asset_digests.add(expected_digest)
        profile = _json_object(
            archive.read(str(_RESOURCE_ROOT / "semantic-profile.json")),
            label="wheel semantic profile",
        )
    expected_profile_digest = profile.get("canonical_sha256")
    profile_body = dict(profile)
    profile_body.pop("canonical_sha256", None)
    if expected_profile_digest != _canonical_digest(profile_body):
        raise ValueError("wheel semantic profile digest mismatch")
    ontology_release_digest = _required_digest(
        profile.get("ontology_release_digest"),
        "semantic profile ontology release digest",
    )
    return _ReleaseIdentity(
        package_version=package_version,
        wheel_digest=wheel_digest,
        asset_manifest_digest=_canonical_digest(manifest),
        semantic_profile_digest=str(expected_profile_digest),
        ontology_release_digest=ontology_release_digest,
    )


def _runtime_config_digest(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise ValueError("--runtime-config MUST be a bounded regular file")
    return _canonical_digest(_json_object(path.read_bytes(), label="runtime config"))


def _json_object(payload: bytes, *, label: str) -> dict[str, object]:
    if len(payload) > _MAX_JSON_BYTES:
        raise ValueError(f"{label} exceeds the byte limit")
    try:
        value = json.loads(payload, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} MUST contain a JSON object")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON object repeats key: {key}")
        result[key] = value
    return result


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _required_path(value: Path | None, option: str) -> Path:
    if value is None:
        raise ValueError(f"{option} is required for release registration")
    return value


def _required_digest(value: object, option: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{option} MUST use sha256:<digest>")
    return value


def _required_revision(value: object) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise ValueError("--source-revision MUST be an exact 40-character revision")
    return value


def _required_text(value: object, option: str) -> str:
    if not isinstance(value, str) or not value.isascii() or not 1 <= len(value) <= 256:
        raise ValueError(f"{option} MUST be bounded non-empty ASCII")
    return value


def _psycopg_dsn(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def main(argv: list[str] | None = None) -> int:
    """Apply one protected lifecycle transition and print its verified receipt."""

    try:
        result = asyncio.run(_run(_parser().parse_args(argv), os.environ))
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, psycopg.Error) as exc:
        print(f"Cost Governance lifecycle failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]