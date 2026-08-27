"""Append-only ledger for provider relationship candidate generations."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.delivery.provider_schema_relationship_generation import (
    ProviderSchemaRelationshipGeneration,
)

_DIGEST_PREFIX = "sha256:"
_DIGEST_LENGTH = 71


class ProviderSchemaRelationshipLedger:
    """Persist immutable proposal generations with an explicit rollback pointer."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def record(self, generation: ProviderSchemaRelationshipGeneration) -> str:
        """Persist a generation and atomically select its proposal-only pointer."""

        with _exclusive_lock(self._root):
            path = self._root / "generations" / f"{generation.generation_digest[7:]}.json"
            payload = _canonical_json(generation.to_mapping()) + b"\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_bytes() != payload:
                raise ProviderSchemaError("provider relationship generation digest collision")
            if not path.exists():
                _atomic_write(path, payload)
            self._write_active(generation.generation_digest)
        return generation.generation_digest

    def rollback(self, generation_digest: str) -> str:
        """Select an existing generation without changing graph or catalog state."""

        _require_digest(generation_digest, "generation digest")
        with _exclusive_lock(self._root):
            path = self._root / "generations" / f"{generation_digest[7:]}.json"
            if not path.is_file():
                raise ProviderSchemaError("provider relationship rollback generation is missing")
            self._write_active(generation_digest)
        return generation_digest

    def read_active(self) -> dict[str, object] | None:
        """Read the active pointer; no pointer means no materialized proposal."""

        path = self._root / "active.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("semantic_promotion") != "proposal_only":
            raise ProviderSchemaError("provider relationship active pointer is invalid")
        generation_digest = raw.get("generation_digest")
        if not isinstance(generation_digest, str):
            raise ProviderSchemaError("provider relationship active pointer digest is invalid")
        try:
            _require_digest(generation_digest, "active generation digest")
        except ValueError as exc:
            raise ProviderSchemaError(
                "provider relationship active pointer digest is invalid"
            ) from exc
        if raw.get("graph_mutation_authority") is not False:
            raise ProviderSchemaError("provider relationship active pointer grants graph authority")
        if raw.get("migration_execution_authority") is not False:
            raise ProviderSchemaError(
                "provider relationship active pointer grants migration authority"
            )
        return raw

    def _write_active(self, generation_digest: str) -> None:
        _atomic_write(
            self._root / "active.json",
            _canonical_json(
                {
                    "generation_digest": generation_digest,
                    "semantic_promotion": "proposal_only",
                    "graph_mutation_authority": False,
                    "migration_execution_authority": False,
                }
            )
            + b"\n",
        )


def _require_digest(value: str, name: str) -> None:
    if len(value) != _DIGEST_LENGTH or not value.startswith(_DIGEST_PREFIX):
        raise ValueError(f"{name} MUST be sha256:<64 lowercase hex>")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise ValueError(f"{name} MUST be sha256:<64 lowercase hex>")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(root: Path) -> Iterator[None]:
    """Serialize record and rollback transactions within this ledger."""

    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(root / ".ledger.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


__all__ = ["ProviderSchemaRelationshipLedger"]
