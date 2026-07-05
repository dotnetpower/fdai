"""Composition root — the ONE place that instantiates concrete implementations.

``core/`` modules never construct adapters; they receive :class:`Container`
instances (or the individual seam Protocols) via arguments. Only entry points
(``__main__``, CLIs, tests) call :func:`default_container`. A per-customer
fork registers its own bindings by exposing its own container factory in its
composition root — it MUST NOT edit ``core/`` or patch upstream defaults.

Design references
-----------------
- ``docs/roadmap/project-structure.md § Customization via Dependency Injection``
- ``.github/instructions/generic-scope.instructions.md``

Only the contract layer is wired in today. Later phases add:

- ``StateStore`` / ``EventBus`` / ``SecretProvider`` / ``WorkloadIdentity``
  seams (Phase-0 WI6),
- ``ModelProvider`` (LLM gateway),
- ``RuleCatalogLoader`` (data-source seam).

Each will be added as a new field on :class:`Container` behind its own
Protocol — the surface here stays additive.
"""

from __future__ import annotations

from dataclasses import dataclass

from .shared.contracts.registry import (
    PackageResourceSchemaRegistry,
    SchemaRegistry,
)
from .shared.contracts.validation import (
    ContractValidator,
    EventValidator,
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)


@dataclass(frozen=True, slots=True)
class Container:
    """Bag of already-bound seams handed to the rest of the app.

    Immutable so a caller cannot silently rewire a seam mid-flight.
    """

    schema_registry: SchemaRegistry
    contract_validator: ContractValidator
    event_validator: EventValidator


def default_container() -> Container:
    """Return the upstream default binding of every seam.

    A fork's own composition root MAY:

    - construct a :class:`Container` with a different :class:`SchemaRegistry`
      (e.g. a remote registry adapter),
    - or wrap :func:`default_container` and override individual fields via
      :func:`dataclasses.replace`.

    This function MUST NOT be called from within ``core/``.
    """
    registry: SchemaRegistry = PackageResourceSchemaRegistry()
    contract_v: ContractValidator = JsonSchemaContractValidator(registry)
    event_v: EventValidator = JsonSchemaEventValidator(contract_v)
    return Container(
        schema_registry=registry,
        contract_validator=contract_v,
        event_validator=event_v,
    )


__all__ = ["Container", "default_container"]
