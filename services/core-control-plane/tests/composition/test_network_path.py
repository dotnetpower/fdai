from __future__ import annotations

from datetime import UTC, datetime

from fdai.composition import build_network_path_runtime
from fdai.core.ontology_platform import ObjectSetService
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.network_path import network_path_function_type
from fdai.shared.contracts.models import OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing import InMemoryOntologyInstanceStore


def test_network_path_runtime_shares_issuer_with_gateway_and_verifier() -> None:
    object_type = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    service = ObjectSetService(
        store=InMemoryOntologyInstanceStore(object_types=(object_type,), link_types=()),
        interfaces=compile_interfaces(
            interfaces=(),
            implementations=(),
            object_types=(object_type,),
        ),
        object_type_names=frozenset({"Resource"}),
    )
    release = build_ontology_release(
        object_types=(object_type,),
        function_types=(network_path_function_type(),),
    )

    binding = build_network_path_runtime(
        service=service,
        object_types={"Resource": object_type},
        ontology_release=release,
        evaluation_cutoff=lambda: datetime(2026, 8, 10, tzinfo=UTC),
    )

    assert binding.gateway is not None
    assert binding.registry is not None
    assert binding.authority.verification_context is binding.authority.verification_context
