from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.delivery.inventory_closure import (
    PostgresInventoryClosureVerifier,
    PostgresInventoryClosureVerifierConfig,
)
from fdai.delivery.inventory_progress import INVENTORY_PROGRESS_GENESIS_DIGEST
from fdai_service_contracts import (
    InventoryProgressFractionBasis,
    InventoryProgressRecord,
    InventoryProgressStage,
    InventoryProgressState,
    inventory_progress_record_digest,
)

NOW = datetime(2026, 9, 16, tzinfo=UTC)


class _Cursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    async def fetchone(self) -> dict[str, object] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, progress: dict[str, object], active: dict[str, object]) -> None:
        self.progress = progress
        self.active = active

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def set_read_only(self, _value: bool) -> None:
        return None

    def transaction(self) -> _Connection:
        return self

    async def execute(self, statement: str, _parameters: object = None) -> _Cursor:
        if "set_config" in statement:
            return _Cursor([])
        if "FROM inventory_progress_event" in statement:
            return _Cursor([{"payload": self.progress}])
        if "FROM inventory_active" in statement:
            return _Cursor([self.active])
        raise AssertionError(statement)


def _progress(generation_digest: str) -> InventoryProgressRecord:
    values: dict[str, object] = {
        "run_id": "genesis.abcdef",
        "attempt_id": "attempt.abcdef",
        "sequence": 1,
        "previous_digest": INVENTORY_PROGRESS_GENESIS_DIGEST,
        "stage": InventoryProgressStage.VERIFY,
        "state": InventoryProgressState.RUNNING,
        "generation_digest": generation_digest,
        "scopes_completed": 0,
        "scopes_total": 1,
        "provider_types_completed": 2,
        "provider_types_total": 2,
        "resources_observed": 4,
        "resources_expected": None,
        "pages_completed": 2,
        "pages_expected": 2,
        "links_observed": 3,
        "unmapped_objects": 1,
        "coverage_gaps": 0,
        "started_at": NOW,
        "last_progress_at": NOW + timedelta(seconds=1),
        "deadline_at": NOW + timedelta(minutes=5),
        "fraction": 0.97,
        "fraction_basis": InventoryProgressFractionBasis.PROVIDER_TYPES,
    }
    return InventoryProgressRecord(
        **values,
        record_digest=inventory_progress_record_digest(**values),
    )


async def test_closure_verifier_binds_exact_active_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = "snapshot-one"
    digest = "sha256:" + hashlib.sha256(generation.encode()).hexdigest()
    progress = _progress(digest)
    active: dict[str, object] = {
        "id": generation,
        "status": "active",
        "source": "arg",
        "observation_kind": "observed",
        "scopes": ["opaque-scope"],
        "resource_types": ["virtual-machine"],
        "metadata": {
            "coverage_scope": "full_provider_scope",
            "provider_scope_coverage": {
                "provider_identity_complete": True,
                "materialized_unmapped_provider_object_count": 1,
            },
            "derived_source_states": [],
            "relationship_drop_reasons": [],
        },
        "promoted_at": NOW + timedelta(seconds=2),
        "resource_count": 4,
        "link_count": 3,
        "unmapped_count": 1,
        "overlay_count": 0,
        "watermarks": {
            "ontology_generation": generation,
            "ontology_projection_watermark": 5,
            "journal_high_watermark": 5,
        },
    }
    connection = _Connection(progress.model_dump(mode="json"), active)
    verifier = PostgresInventoryClosureVerifier(
        config=PostgresInventoryClosureVerifierConfig(dsn="postgresql://test")
    )

    async def connect() -> Any:
        return connection

    monkeypatch.setattr(verifier, "_connect", connect)
    receipt = await verifier.verify(run_id=progress.run_id, attempt_id=progress.attempt_id)

    assert receipt.active_generation_matches is True
    assert receipt.generation_digest == digest

    connection.progress = _progress("sha256:" + "f" * 64).model_dump(mode="json")
    with pytest.raises(ValueError, match="active_generation"):
        await verifier.verify(run_id=progress.run_id, attempt_id=progress.attempt_id)


async def test_closure_verifier_rejects_broken_progress_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress = _progress("sha256:" + "a" * 64)
    connection = _Connection(progress.model_dump(mode="json"), {})
    second_values = progress.model_dump(mode="python", exclude={"record_digest"})
    second_values.update(sequence=3, previous_digest=progress.record_digest)
    second = InventoryProgressRecord(
        **second_values,
        record_digest=inventory_progress_record_digest(**second_values),
    )

    class _BrokenConnection(_Connection):
        async def execute(self, statement: str, _parameters: object = None) -> _Cursor:
            if "FROM inventory_progress_event" in statement:
                return _Cursor(
                    [
                        {"payload": progress.model_dump(mode="json")},
                        {"payload": second.model_dump(mode="json")},
                    ]
                )
            return await super().execute(statement, _parameters)

    verifier = PostgresInventoryClosureVerifier(
        config=PostgresInventoryClosureVerifierConfig(dsn="postgresql://test")
    )

    async def connect() -> Any:
        return _BrokenConnection(connection.progress, connection.active)

    monkeypatch.setattr(verifier, "_connect", connect)
    with pytest.raises(ValueError, match="chain is invalid"):
        await verifier.latest_progress(run_id=progress.run_id, attempt_id=progress.attempt_id)
