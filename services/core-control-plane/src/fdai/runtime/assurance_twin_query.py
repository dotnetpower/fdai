"""Runtime composition for strict Assurance Twin semantic query compilation."""

from __future__ import annotations

from fdai.composition import Container
from fdai.core.assurance_twin import (
    AssuranceTwinSemanticQueryCoordinator,
    DeterministicPatternCompiler,
    QueryVerifier,
)
from fdai.rule_catalog.schema.resource_type import ResourceTypeRegistry


def build_assurance_twin_semantic_query(
    container: Container,
    *,
    resource_types: ResourceTypeRegistry,
) -> AssuranceTwinSemanticQueryCoordinator:
    """Bind injected compiler/discovery seams with an explicit unavailable default."""

    compiler = container.assurance_twin_query_compiler or DeterministicPatternCompiler(
        resource_types
    )
    revision = (
        type(compiler).__name__
        if container.assurance_twin_query_compiler is not None
        else "unavailable-v1"
    )
    return AssuranceTwinSemanticQueryCoordinator(
        compiler=compiler,
        verifier=QueryVerifier(resource_types, require_compiler_evidence=True),
        compiler_revision=revision,
        discovery_sink=container.assurance_twin_discovery_sink,
    )


__all__ = ["build_assurance_twin_semantic_query"]
