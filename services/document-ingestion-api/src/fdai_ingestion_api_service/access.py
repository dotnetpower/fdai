"""Claims-backed access policy for governed document collections."""

from fdai_service_contracts import DocumentAccessDeniedError, DocumentVersion

_CONTRIBUTOR_MARKERS = frozenset({"role:Contributor", "role:Approver", "role:Owner"})
_OWNER_MARKERS = frozenset({"role:Owner"})


class ClaimsDocumentAccessProvider:
    """Enforce collection and version access from verified role/group markers."""

    async def authorize_create(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        collection_id: str,
    ) -> None:
        if not actor_groups.intersection(_CONTRIBUTOR_MARKERS):
            raise DocumentAccessDeniedError("collection contributor access is required")

    async def authorize_read(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        allowed = frozenset(version.access.reader_groups) | _CONTRIBUTOR_MARKERS
        if actor_id != version.uploader_id and not actor_groups.intersection(allowed):
            raise DocumentAccessDeniedError("document metadata access is denied")

    async def authorize_delete(
        self,
        *,
        actor_id: str,
        actor_groups: frozenset[str],
        version: DocumentVersion,
    ) -> None:
        if actor_id != version.uploader_id and not actor_groups.intersection(_OWNER_MARKERS):
            raise DocumentAccessDeniedError("document delete access is denied")
