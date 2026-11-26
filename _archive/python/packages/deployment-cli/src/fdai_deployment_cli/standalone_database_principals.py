"""Principal selection for the in-cluster PostgreSQL stage of an AKS installation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai_deployment_cli.standalone_operational_evidence import (
    runtime_principal_ids_with_operational_evidence_verifier,
)


def database_reader_principals(
    identities: Mapping[str, Any],
) -> tuple[set[str], str | None, str | None]:
    """Return the DSN reader principals for the in-cluster database stage.

    Core and inventory always run. The Operator, executor, and document-ingestion identities exist
    only when their product option is selected, so an absent one is granted nothing instead of
    stopping the stage. A present identity must still be well formed.
    """

    names = tuple(
        name
        for name in ("core", "operator", "executor", "inventory")
        if name in {"core", "inventory"} or identities.get(name) is not None
    )

    def optional(name: str, label: str) -> str | None:
        value = identities.get(name)
        if value is None:
            return None
        if not isinstance(value, dict) or not isinstance(value.get("principal_id"), str):
            raise ValueError(f"{label} is invalid")
        return str(value["principal_id"])

    return (
        runtime_principal_ids_with_operational_evidence_verifier(identities, names),
        optional("ingestion", "ingestion runtime identity"),
        optional("ingestion_worker", "ingestion worker runtime identity"),
    )
