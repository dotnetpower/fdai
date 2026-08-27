"""Append-only ledger for provider relationship candidate generations."""

from __future__ import annotations

import json
import os
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
    temporary = path.with_name(f".{path.name}.staged")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


__all__ = ["ProviderSchemaRelationshipLedger"]
