"""Reclaim only retired, terminal-audited ontology index projection namespaces."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from fdai.shared.providers.state_store import StateStore

from .ontology_index_lifecycle import IndexGeneration, IndexTerminal, OntologyIndexLifecycle
from .ontology_snapshot_store import _digest


async def reclaim_retired_index(
    *,
    store: StateStore,
    lifecycle: OntologyIndexLifecycle,
    target: IndexGeneration,
) -> int:
    """Leave one immutable retirement marker per namespace and remove only derived rows.

    Eligibility is already removed by owner CAS and sealed by Saga. Source-bound
    retirement prevents a concurrent new activation from adopting these same rows.
    Reclamation is retryable and touches neither audit nor command history.
    """
    async with asyncio.timeout(10):
        pointer = await lifecycle.read(target.scope)
        terminal = pointer.terminal
        if (
            target == pointer.active
            or target in pointer.retained
            or terminal is None
            or terminal.command.operation != "retire"
            or terminal.command.target != target
        ):
            raise ValueError("ontology reclamation requires the exact retired terminal target")
        raw_seal = await store.read_state(
            f"ontology-context-evidence:v1:terminal-seal:{terminal.command.digest}"
        )
        if (
            raw_seal is None
            or not isinstance(raw_seal.get("terminal"), Mapping)
            or IndexTerminal.model_validate(raw_seal["terminal"]) != terminal
        ):
            raise ValueError("ontology reclamation requires matching Saga terminal audit")
        retirement = await store.read_state(
            f"ontology-context-index:v1:{target.scope.digest}:retired:{target.snapshot_digest}"
        )
        if retirement != {
            "snapshot_digest": target.snapshot_digest,
            "command_digest": terminal.command.digest,
        }:
            raise ValueError("ontology reclamation requires a durable retirement fence")
        binding = _digest(
            {
                "snapshot_digest": target.snapshot_digest,
                "generation_digest": target.generation_digest,
            }
        )
        prefixes = (
            f"ontology-semantic-snapshot:v1:{target.snapshot_digest}:",
            f"ontology-semantic-vectors:v1:{binding}:",
            f"ontology-semantic-vectors:v1:{target.vector_digest}:",
        )
        marker: dict[str, Any] = {
            "retired_snapshot_digest": target.snapshot_digest,
            "retirement_command_digest": terminal.command.digest,
        }
        deleted = 0
        for prefix in prefixes:
            key = prefix + "retired"
            if not await store.write_state_if_absent(key, marker):
                if await store.read_state(key) != marker:
                    raise ValueError("ontology reclamation retirement marker conflict")
                await store.write_state(key, marker)
            deleted += await store.delete_states_beyond(prefix, retain_newest=1)
            remaining, total = await store.read_state_page(prefix, limit=2)
            if total != 1 or remaining != (marker,):
                raise ValueError(
                    "ontology reclamation did not retain exactly its retirement marker"
                )
        return deleted
