"""Durably mirror the filesystem provider-schema ledger through StateStore."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.shared.providers.state_store import StateStore

_MANIFEST_KEY = "provider-schema-ledger:manifest"
_BLOB_PREFIX = "provider-schema-ledger:blob:"
_MAX_FILE_BYTES = 20 * 1024 * 1024


class StateStoreProviderSchemaLedger:
    """Hydrate and persist one verified ledger generation through durable JSON state."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def hydrate(self, root: Path) -> bool:
        """Restore the latest complete durable generation into an empty local root."""

        manifest = await self._store.read_state(_MANIFEST_KEY)
        if manifest is None:
            return False
        entries = _manifest_entries(manifest)
        if any(root.iterdir()):
            raise ProviderSchemaError("provider schema hydration root MUST be empty")
        for relative_path, digest in entries:
            blob = await self._store.read_state(f"{_BLOB_PREFIX}{digest}")
            if blob is None:
                raise ProviderSchemaError("provider schema durable blob is missing")
            content = blob.get("content")
            if not isinstance(content, str):
                raise ProviderSchemaError("provider schema durable blob content is invalid")
            payload = content.encode("utf-8")
            if _digest(payload) != digest:
                raise ProviderSchemaError("provider schema durable blob digest mismatch")
            target = root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        return True

    async def persist(self, root: Path) -> str:
        """Store immutable blobs first and atomically publish their complete manifest last."""

        files = tuple(sorted(path for path in root.rglob("*") if path.is_file()))
        if not files:
            raise ProviderSchemaError("provider schema ledger generation is empty")
        entries: list[dict[str, str]] = []
        for path in files:
            relative_path = path.relative_to(root).as_posix()
            _bounded_path(relative_path)
            payload = path.read_bytes()
            if len(payload) > _MAX_FILE_BYTES:
                raise ProviderSchemaError("provider schema ledger file exceeds durable bound")
            try:
                content = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProviderSchemaError("provider schema ledger file MUST be UTF-8") from exc
            digest = _digest(payload)
            record = {
                "schema_version": "1.0.0",
                "digest": digest,
                "content": content,
                "grants_authority": False,
            }
            inserted = await self._store.write_state_if_absent(
                f"{_BLOB_PREFIX}{digest}",
                record,
            )
            if not inserted:
                existing = await self._store.read_state(f"{_BLOB_PREFIX}{digest}")
                if existing != record:
                    raise ProviderSchemaError("provider schema durable blob conflicts")
            entries.append({"path": relative_path, "digest": digest})
        manifest = {
            "schema_version": "1.0.0",
            "entries": entries,
            "generation_digest": _digest(
                "\n".join(f"{item['path']}\0{item['digest']}" for item in entries).encode("utf-8")
            ),
            "grants_authority": False,
        }
        await self._store.write_state(_MANIFEST_KEY, manifest)
        return str(manifest["generation_digest"])


def _manifest_entries(manifest: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    if manifest.get("schema_version") != "1.0.0" or manifest.get("grants_authority") is not False:
        raise ProviderSchemaError("provider schema durable manifest is invalid")
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
        raise ProviderSchemaError("provider schema durable manifest entries are invalid")
    entries: list[tuple[str, str]] = []
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise ProviderSchemaError("provider schema durable manifest entry is invalid")
        path = raw.get("path")
        digest = raw.get("digest")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ProviderSchemaError("provider schema durable manifest entry is invalid")
        _bounded_path(path)
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ProviderSchemaError("provider schema durable manifest digest is invalid")
        entries.append((path, digest))
    if tuple(sorted(entries)) != tuple(entries) or len(entries) != len(set(entries)):
        raise ProviderSchemaError("provider schema durable manifest MUST be sorted and unique")
    expected = _digest("\n".join(f"{path}\0{digest}" for path, digest in entries).encode("utf-8"))
    if manifest.get("generation_digest") != expected:
        raise ProviderSchemaError("provider schema durable manifest digest mismatch")
    return tuple(entries)


def _bounded_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ProviderSchemaError("provider schema durable path is invalid")


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = ["StateStoreProviderSchemaLedger"]
