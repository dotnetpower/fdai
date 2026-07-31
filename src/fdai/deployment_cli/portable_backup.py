"""Portable, secret-free deployment metadata backup and restore."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fdai.deployment_cli.onboarding import DeploymentEnvironment

BACKUP_SCHEMA: Final = "fdai.deployment.portable-backup.v1"
BACKUP_RESULT_SCHEMA: Final = "fdai.deployment-cli.portable-backup-result.v1"
REFERENCES_SCHEMA: Final = "fdai.deployment.portable-references.v1"
AUDIT_METADATA_SCHEMA: Final = "fdai.deployment.portable-audit-metadata.v1"
USER_CONTEXT_SCHEMA: Final = "fdai.deployment.portable-user-context.v1"

_CONFIG_NAME: Final = "configuration.json"
_REFERENCES_NAME: Final = "references.json"
_AUDIT_NAME: Final = "audit-metadata.json"
_USER_CONTEXT_NAME: Final = "user-context.json"
_MANIFEST_NAME: Final = "manifest.json"
_PAYLOAD_NAMES: Final = (
    _CONFIG_NAME,
    _REFERENCES_NAME,
    _AUDIT_NAME,
    _USER_CONTEXT_NAME,
)
_ARCHIVE_NAMES: Final = frozenset((*_PAYLOAD_NAMES, _MANIFEST_NAME))
_MAX_SOURCE_BYTES: Final = 4 * 1024 * 1024
_MAX_ARCHIVE_BYTES: Final = 16 * 1024 * 1024
_MAX_RECORDS: Final = 10_000
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,1023}$")
_SECRET_KEY_PARTS: Final = (
    "password",
    "private_key",
    "access_key",
    "connection_string",
    "token",
    "secret_value",
)
_SECRET_VALUE_PATTERNS: Final = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(
        r"(?:password|passwd|access[_-]?key|accountkey|sharedaccesssignature|"
        r"client[_-]?secret|secret[_-]?value|token)\s*[:=]\s*[^\s,;]+",
        re.IGNORECASE,
    ),
    re.compile(r"authorization\s*[:=]\s*bearer\s+[^\s,;]+", re.IGNORECASE),
)


class _PortableModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PortableReference(_PortableModel):
    kind: Literal["secret", "document", "policy", "workflow", "channel", "bundle"]
    name: Annotated[str, Field(min_length=1, max_length=128)]
    ref: Annotated[str, Field(min_length=1, max_length=1024)]

    @model_validator(mode="after")
    def validate_reference(self) -> PortableReference:
        if _SAFE_REF.fullmatch(self.ref) is None:
            raise ValueError("portable reference contains unsupported characters")
        return self


class PortableReferences(_PortableModel):
    schema_version: Literal["fdai.deployment.portable-references.v1"] = REFERENCES_SCHEMA
    records: tuple[PortableReference, ...] = Field(max_length=_MAX_RECORDS)


class PortableAuditMetadata(_PortableModel):
    schema_version: Literal["fdai.deployment.portable-audit-metadata.v1"] = AUDIT_METADATA_SCHEMA
    source_schema: Annotated[str, Field(min_length=1, max_length=128)]
    last_sequence: Annotated[int, Field(ge=0)]
    record_count: Annotated[int, Field(ge=0)]
    head_entry_hash: str | None = None

    @model_validator(mode="after")
    def validate_checkpoint(self) -> PortableAuditMetadata:
        if self.last_sequence == 0:
            if self.head_entry_hash is not None or self.record_count != 0:
                raise ValueError("empty audit metadata cannot declare records or a head hash")
        elif self.head_entry_hash is None or _DIGEST.fullmatch(self.head_entry_hash) is None:
            raise ValueError("non-empty audit metadata requires a SHA-256 head hash")
        if self.record_count < self.last_sequence:
            raise ValueError("audit record_count cannot be lower than last_sequence")
        return self


class PortableUserPreference(_PortableModel):
    principal_ref: Annotated[str, Field(min_length=1, max_length=256)]
    locale: Literal["en", "ko"] = "en"
    verbosity: Literal["concise", "detailed"] = "concise"
    answer_detail: Literal["brief", "standard", "deep"] = "standard"
    answer_format: Literal[
        "prose",
        "bullets",
        "numbered_steps",
        "table",
        "chart",
        "checklist",
        "mixed",
    ] = "prose"
    answer_preferences_enabled: bool = True
    answer_intent_detail: dict[str, Literal["brief", "standard", "deep"]] = Field(
        default_factory=dict
    )
    answer_intent_format: dict[
        str,
        Literal["prose", "bullets", "numbered_steps", "table", "chart", "checklist", "mixed"],
    ] = Field(default_factory=dict)
    timezone: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    share_with_learner: bool = False
    revision: Annotated[int, Field(ge=0)] = 0
    updated_at: datetime | None = None


class PortableUserMemory(_PortableModel):
    principal_ref: Annotated[str, Field(min_length=1, max_length=256)]
    memory_id: Annotated[str, Field(min_length=1, max_length=256)]
    category: Literal["preference", "context", "goal"]
    body: Annotated[str, Field(min_length=1, max_length=16_384)]
    source_ref: Annotated[str, Field(min_length=1, max_length=1024)]
    consented_at: datetime
    created_at: datetime
    expires_at: datetime | None = None
    superseded_by: Annotated[str, Field(min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> PortableUserMemory:
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("portable user memory expiry must follow creation")
        if self.superseded_by == self.memory_id:
            raise ValueError("portable user memory cannot supersede itself")
        return self


class PortableUserContext(_PortableModel):
    schema_version: Literal["fdai.deployment.portable-user-context.v1"] = USER_CONTEXT_SCHEMA
    preferences: tuple[PortableUserPreference, ...] = Field(default=(), max_length=_MAX_RECORDS)
    memories: tuple[PortableUserMemory, ...] = Field(default=(), max_length=_MAX_RECORDS)


class PortableBackupManifest(_PortableModel):
    schema_version: Literal["fdai.deployment.portable-backup.v1"] = BACKUP_SCHEMA
    archive_format: Literal["zip-stored"] = "zip-stored"
    files: dict[str, str]

    @model_validator(mode="after")
    def validate_files(self) -> PortableBackupManifest:
        if set(self.files) != set(_PAYLOAD_NAMES):
            raise ValueError("portable backup manifest has an unexpected file set")
        if any(_DIGEST.fullmatch(digest) is None for digest in self.files.values()):
            raise ValueError("portable backup manifest contains an invalid digest")
        return self


class PortableBackupResult(_PortableModel):
    schema_version: Literal["fdai.deployment-cli.portable-backup-result.v1"] = BACKUP_RESULT_SCHEMA
    operation: Literal["create", "restore"]
    archive_digest: str
    file_count: int
    path: str

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))


class PortableBackupError(RuntimeError):
    """A portable backup operation failed before publishing restored state."""


def create_portable_backup(
    *,
    config_path: Path,
    references_path: Path,
    audit_metadata_path: Path,
    user_context_path: Path,
    archive_path: Path,
    force: bool = False,
) -> PortableBackupResult:
    """Validate and package the portable state allowlist into a private archive."""
    payloads = {
        _CONFIG_NAME: _load_model(config_path, DeploymentEnvironment, "configuration"),
        _REFERENCES_NAME: _load_model(references_path, PortableReferences, "portable references"),
        _AUDIT_NAME: _load_model(audit_metadata_path, PortableAuditMetadata, "audit metadata"),
        _USER_CONTEXT_NAME: _load_model(user_context_path, PortableUserContext, "user context"),
    }
    encoded = {name: _canonical_model(model) for name, model in payloads.items()}
    for name, payload in encoded.items():
        _assert_export_safe(payload, name)
    manifest = PortableBackupManifest(
        files={name: hashlib.sha256(payload).hexdigest() for name, payload in encoded.items()}
    )
    members = {**encoded, _MANIFEST_NAME: _canonical_model(manifest)}
    _write_archive(archive_path, members, force=force)
    return PortableBackupResult(
        operation="create",
        archive_digest=_file_digest(archive_path),
        file_count=len(encoded),
        path=str(archive_path),
    )


def restore_portable_backup(*, archive_path: Path, destination: Path) -> PortableBackupResult:
    """Verify a portable archive and atomically restore it into a new directory."""
    members = _read_archive(archive_path)
    manifest = _validate_manifest(members)
    _validate_payloads(members)
    for name in _PAYLOAD_NAMES:
        if hashlib.sha256(members[name]).hexdigest() != manifest.files[name]:
            raise PortableBackupError("portable backup payload digest mismatch")

    destination_parent = destination.parent
    destination_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise PortableBackupError("restore destination already exists")
    staging = Path(tempfile.mkdtemp(prefix=".fdai-restore-", dir=destination_parent))
    try:
        staging.chmod(0o700)
        for name in _PAYLOAD_NAMES:
            _write_private_file(staging / name, members[name])
        os.replace(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return PortableBackupResult(
        operation="restore",
        archive_digest=_file_digest(archive_path),
        file_count=len(_PAYLOAD_NAMES),
        path=str(destination),
    )


def _load_model(path: Path, model_type: type[BaseModel], label: str) -> BaseModel:
    payload = _read_guarded_file(path, label)
    try:
        return model_type.model_validate_json(payload)
    except ValidationError as exc:
        raise PortableBackupError(f"{label} is invalid") from exc


def _canonical_model(model: BaseModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def _read_guarded_file(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PortableBackupError(f"{label} must be a regular file")
    if path.stat().st_size > _MAX_SOURCE_BYTES:
        raise PortableBackupError(f"{label} exceeds the size limit")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PortableBackupError(f"{label} is unreadable") from exc


def _assert_export_safe(payload: bytes, label: str) -> None:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PortableBackupError(f"{label} is not valid JSON") from exc
    if _contains_secret_key(value):
        raise PortableBackupError(f"{label} contains a secret-like field")
    text = payload.decode("utf-8")
    if any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS):
        raise PortableBackupError(f"{label} contains a secret-like value")
    if _contains_terraform_state(value):
        raise PortableBackupError(f"{label} contains Terraform state")


def _contains_secret_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower()
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_key(child) for child in value)
    return False


def _contains_terraform_state(value: object) -> bool:
    if isinstance(value, dict):
        normalized_keys = {str(key).lower() for key in value}
        if "terraform_version" in normalized_keys and (
            "resources" in normalized_keys or "lineage" in normalized_keys
        ):
            return True
        return any(_contains_terraform_state(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_terraform_state(child) for child in value)
    if isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            nested = json.loads(value)
        except json.JSONDecodeError:
            return False
        return _contains_terraform_state(nested)
    return False


def _write_archive(path: Path, members: dict[str, bytes], *, force: bool) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".portable-backup-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with (
            os.fdopen(descriptor, "w+b") as stream,
            zipfile.ZipFile(
                stream, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True
            ) as archive,
        ):
            for name in sorted(members):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o600) << 16
                archive.writestr(info, members[name])
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary_path, path)
        else:
            try:
                os.link(temporary_path, path)
            except FileExistsError as exc:
                raise PortableBackupError("backup archive already exists; use --force") from exc
            temporary_path.unlink()
        path.chmod(0o600)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _read_archive(path: Path) -> dict[str, bytes]:
    if path.is_symlink() or not path.is_file():
        raise PortableBackupError("backup archive must be a regular file")
    if path.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise PortableBackupError("backup archive exceeds the size limit")
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if len(infos) != len(_ARCHIVE_NAMES) or {info.filename for info in infos} != set(
                _ARCHIVE_NAMES
            ):
                raise PortableBackupError("backup archive has an unexpected file set")
            members: dict[str, bytes] = {}
            for info in infos:
                if (
                    info.is_dir()
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.file_size > _MAX_SOURCE_BYTES
                ):
                    raise PortableBackupError("backup archive member is invalid")
                members[info.filename] = archive.read(info)
            return members
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise PortableBackupError("backup archive is invalid or unreadable") from exc


def _validate_manifest(members: dict[str, bytes]) -> PortableBackupManifest:
    try:
        return PortableBackupManifest.model_validate_json(members[_MANIFEST_NAME])
    except ValidationError as exc:
        raise PortableBackupError("portable backup manifest is invalid") from exc


def _validate_payloads(members: dict[str, bytes]) -> None:
    validators: tuple[tuple[str, type[BaseModel]], ...] = (
        (_CONFIG_NAME, DeploymentEnvironment),
        (_REFERENCES_NAME, PortableReferences),
        (_AUDIT_NAME, PortableAuditMetadata),
        (_USER_CONTEXT_NAME, PortableUserContext),
    )
    for name, model_type in validators:
        try:
            model_type.model_validate_json(members[name])
        except ValidationError as exc:
            raise PortableBackupError(f"restored {name} is invalid") from exc
        _assert_export_safe(members[name], name)


def _write_private_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AUDIT_METADATA_SCHEMA",
    "BACKUP_RESULT_SCHEMA",
    "BACKUP_SCHEMA",
    "REFERENCES_SCHEMA",
    "USER_CONTEXT_SCHEMA",
    "PortableAuditMetadata",
    "PortableBackupError",
    "PortableBackupManifest",
    "PortableBackupResult",
    "PortableReference",
    "PortableReferences",
    "PortableUserContext",
    "PortableUserMemory",
    "PortableUserPreference",
    "create_portable_backup",
    "restore_portable_backup",
]
