"""Principal-scoped query manifest projection for semantic planning."""

from __future__ import annotations

from collections.abc import Sequence

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform import QueryManifest, build_query_manifest
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyActionType,
    OntologyFunctionType,
    OntologyInterfaceType,
    OntologyLinkType,
    OntologyObjectType,
    OntologyRelease,
)

from .session import Principal, Role

_ROLE_MAP = {
    Role.READER: CeilingRole.READER,
    Role.CONTRIBUTOR: CeilingRole.CONTRIBUTOR,
    Role.APPROVER: CeilingRole.APPROVER,
    Role.OWNER: CeilingRole.OWNER,
}


class CatalogQueryManifestProvider:
    """Build immutable planner metadata from one exact loaded catalog release."""

    def __init__(
        self,
        *,
        release: OntologyRelease,
        object_types: Sequence[OntologyObjectType] = (),
        link_types: Sequence[OntologyLinkType] = (),
        interfaces: Sequence[OntologyInterfaceType] = (),
        action_types: Sequence[OntologyActionType] = (),
        functions: Sequence[OntologyFunctionType] = (),
    ) -> None:
        self._release = release
        self._object_types = tuple(object_types)
        self._link_types = tuple(link_types)
        self._interfaces = tuple(interfaces)
        self._action_types = tuple(action_types)
        self._functions = tuple(functions)

    def manifest_for(self, *, principal: Principal, purpose: str) -> QueryManifest:
        """Return only declarations readable by the verified role and purpose."""

        try:
            role = _ROLE_MAP[principal.role]
        except KeyError as exc:
            raise PermissionError("break-glass principals cannot use semantic planning") from exc
        scope_digest = content_digest(
            {
                "principal_id": principal.id,
                "role": principal.role.value,
                "purpose": purpose,
            }
        )
        return build_query_manifest(
            release=self._release,
            principal_role=role,
            purposes=(purpose,),
            principal_scope_digest=scope_digest,
            object_types=self._object_types,
            link_types=self._link_types,
            interfaces=self._interfaces,
            action_types=self._action_types,
            functions=self._functions,
        )


__all__ = ["CatalogQueryManifestProvider"]
