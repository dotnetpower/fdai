"""Production composition for issuer-backed network path queries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from fdai.core.ontology_platform import ObjectSetService, OntologyFunctionRegistry
from fdai.core.ontology_platform.network_path import (
    network_path_function,
    network_path_function_type,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.delivery.ontology_query_receipts import HmacNetworkQueryReceiptAuthority
from fdai.shared.contracts.models import OntologyObjectType, OntologyRelease


@dataclass(frozen=True, slots=True)
class NetworkPathRuntimeBinding:
    """One shared issuer, secured gateway, and exact-release function registry."""

    gateway: SecuredObjectSetQueryGateway
    registry: OntologyFunctionRegistry
    authority: HmacNetworkQueryReceiptAuthority


def build_network_path_runtime(
    *,
    service: ObjectSetService,
    object_types: Mapping[str, OntologyObjectType],
    ontology_release: OntologyRelease,
    evaluation_cutoff: Callable[[], datetime],
    max_as_of_skew: timedelta = timedelta(0),
    authority: HmacNetworkQueryReceiptAuthority | None = None,
) -> NetworkPathRuntimeBinding:
    """Build an authenticated A0 network-query runtime with no provider I/O."""

    selected_authority = authority or HmacNetworkQueryReceiptAuthority()
    declaration = network_path_function_type()
    registry = OntologyFunctionRegistry(release=ontology_release)
    registry.register_contextual(
        declaration,
        network_path_function(
            ontology_release,
            receipt_verifier=selected_authority,
            verification_context=selected_authority.verification_context,
        ),
    )
    gateway = SecuredObjectSetQueryGateway(
        service=service,
        object_types=object_types,
        ontology_release=ontology_release,
        evaluation_cutoff=evaluation_cutoff,
        max_as_of_skew=max_as_of_skew,
        receipt_issuer=selected_authority,
    )
    return NetworkPathRuntimeBinding(
        gateway=gateway,
        registry=registry,
        authority=selected_authority,
    )


__all__ = ["NetworkPathRuntimeBinding", "build_network_path_runtime"]
