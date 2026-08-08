"""Read-only platform capability manifest."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.shared.contracts.models import OntologyActionType, OntologyRelease

from .interfaces import CompiledInterfaceCatalog
from .kinetics import OntologyFunctionType


def platform_manifest(
    *,
    release: OntologyRelease,
    interfaces: CompiledInterfaceCatalog,
    action_types: Sequence[OntologyActionType],
    functions: Sequence[OntologyFunctionType],
) -> dict[str, object]:
    return {
        "release_digest": release.digest,
        "interfaces": {
            name: list(interfaces.resolve(name)) for name in sorted(interfaces.interfaces)
        },
        "action_types": [item.name for item in sorted(action_types, key=lambda item: item.name)],
        "functions": [item.name for item in sorted(functions, key=lambda item: item.name)],
        "mutation_authority": False,
        "write_surface": "typed_proposal",
    }


__all__ = ["platform_manifest"]
