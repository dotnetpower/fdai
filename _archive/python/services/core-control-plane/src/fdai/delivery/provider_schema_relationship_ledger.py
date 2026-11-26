"""Append-only ledger for provider relationship candidate generations."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fdai.core.ontology_platform.direction_shadow import (
    DirectionGraphGeneration,
    DirectionPromotionAssessment,
    DirectionShadowReceipt,
)
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
            _verify_generation_artifact(path, generation_digest)
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
        generation_path = self._root / "generations" / f"{generation_digest[7:]}.json"
        if not generation_path.is_file():
            raise ProviderSchemaError("provider relationship active generation is missing")
        if raw.get("graph_mutation_authority") is not False:
            raise ProviderSchemaError("provider relationship active pointer grants graph authority")
        if raw.get("migration_execution_authority") is not False:
            raise ProviderSchemaError(
                "provider relationship active pointer grants migration authority"
            )
        return raw

    def record_promotion_review(
        self,
        *,
        assessment: DirectionPromotionAssessment,
        receipt: DirectionShadowReceipt,
        prior: DirectionGraphGeneration,
        aligned: DirectionGraphGeneration,
    ) -> str:
        """Persist immutable comparison, context, and reviewed proposal history."""

        if assessment.comparison_receipt_digest != receipt.receipt_digest:
            raise ProviderSchemaError("promotion assessment does not match comparison receipt")
        if (
            assessment.prior_generation_digest != prior.generation_digest
            or receipt.legacy_generation_digest != prior.generation_digest
            or assessment.aligned_generation_digest != aligned.generation_digest
            or receipt.aligned_generation_digest != aligned.generation_digest
        ):
            raise ProviderSchemaError("promotion review generation identity mismatch")
        with _exclusive_lock(self._root):
            _write_immutable_json(
                self._root / "direction-contexts" / f"{prior.generation_digest[7:]}.json",
                prior.to_mapping(),
                collision_message="prior direction context digest collision",
            )
            _write_immutable_json(
                self._root / "direction-contexts" / f"{aligned.generation_digest[7:]}.json",
                aligned.to_mapping(),
                collision_message="aligned direction context digest collision",
            )
            _write_immutable_json(
                self._root / "direction-comparisons" / f"{receipt.receipt_digest[7:]}.json",
                receipt.to_mapping(),
                collision_message="direction comparison digest collision",
            )
            _write_immutable_json(
                self._root
                / "direction-promotion-reviews"
                / f"{assessment.assessment_digest[7:]}.json",
                assessment.to_mapping(),
                collision_message="direction promotion review digest collision",
            )
            history = self._read_promotion_history()
            if not any(
                item.get("assessment_digest") == assessment.assessment_digest for item in history
            ):
                history.append(
                    {
                        "aligned_generation_digest": aligned.generation_digest,
                        "assessment_digest": assessment.assessment_digest,
                        "comparison_receipt_digest": receipt.receipt_digest,
                        "decision": assessment.decision.value,
                        "graph_mutation_authority": False,
                        "migration_execution_authority": False,
                        "prior_generation_digest": prior.generation_digest,
                        "proposal_ready": assessment.proposal_ready,
                        "rebuild_pointer": {
                            "authoritative_generation_ref": (
                                assessment.rebuild_pointer.authoritative_generation_ref
                            ),
                            "mutation_authority": (assessment.rebuild_pointer.mutation_authority),
                            "rebuild_procedure_ref": (
                                assessment.rebuild_pointer.rebuild_procedure_ref
                            ),
                            "restores_deleted_rows": (
                                assessment.rebuild_pointer.restores_deleted_rows
                            ),
                            "strategy": assessment.rebuild_pointer.strategy,
                        },
                        "regression_receipt_digests": list(assessment.regression_receipt_digests),
                        "requested_by": assessment.requested_by,
                        "reviewed_at": assessment.reviewed_at.isoformat(),
                        "reviewed_by": assessment.reviewed_by,
                    }
                )
                _append_json_line(
                    self._root / "direction-promotion-history.jsonl",
                    history[-1],
                )
        return str(assessment.assessment_digest)

    def read_promotion_history(self) -> tuple[dict[str, object], ...]:
        """Return immutable reviewed proposal history without activation authority."""

        history = self._read_promotion_history()
        if any(
            item.get("graph_mutation_authority") is not False
            or item.get("migration_execution_authority") is not False
            for item in history
        ):
            raise ProviderSchemaError("direction promotion history grants mutation authority")
        return tuple(history)

    def _read_promotion_history(self) -> list[dict[str, object]]:
        path = self._root / "direction-promotion-history.jsonl"
        if not path.exists():
            return []
        history: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProviderSchemaError("direction promotion history is invalid") from exc
            if not isinstance(raw, dict):
                raise ProviderSchemaError("direction promotion history is invalid")
            history.append(raw)
        return history

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


def _verify_generation_artifact(path: Path, expected_digest: str) -> None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderSchemaError("provider relationship generation artifact is invalid") from exc
    if not isinstance(raw, dict) or raw.get("generation_digest") != expected_digest:
        raise ProviderSchemaError("provider relationship generation artifact digest mismatch")
    material = {key: value for key, value in raw.items() if key != "generation_digest"}
    actual_digest = "sha256:" + hashlib.sha256(_canonical_json(material)).hexdigest()
    if actual_digest != expected_digest:
        raise ProviderSchemaError("provider relationship generation artifact digest mismatch")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _write_immutable_json(
    path: Path,
    value: object,
    *,
    collision_message: str,
) -> None:
    payload = _canonical_json(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ProviderSchemaError(collision_message)
        return
    _atomic_write(path, payload)


def _append_json_line(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(_canonical_json(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


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
