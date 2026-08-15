"""Chat `document_refs` stay bounded, principal-scoped, and fail closed."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fdai_operator_service.families.conversation.contracts import PrincipalScope
from fdai_operator_service.families.conversation.document_refs import (
    ACCESS_DENIED_MESSAGE,
    MAX_DOCUMENT_REFS,
    DocumentRef,
    DocumentRefAccessDeniedError,
    DocumentRefIntegrityError,
    DocumentRefResolverUnavailableError,
    DocumentRefSyntaxError,
    parse_document_refs,
    resolve_document_refs,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"
VERSION_ID = "22222222-2222-4222-8222-222222222222"
OTHER_VERSION_ID = "33333333-3333-4333-8333-333333333333"
SCOPE = PrincipalScope(subject_id="principal-1", roles=frozenset({"operator"}))


def _body(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"document_id": document, "version_id": version} for document, version in pairs]


class _Resolver:
    def __init__(self, *, owned: set[tuple[str, str]] | None = None) -> None:
        self.owned = owned if owned is not None else {(DOCUMENT_ID, VERSION_ID)}
        self.calls: list[str] = []

    async def resolve(
        self,
        *,
        principal_id: str,
        refs: Sequence[DocumentRef],
    ) -> Sequence[str]:
        self.calls.append(principal_id)
        for ref in refs:
            if (str(ref.document_id), str(ref.version_id)) not in self.owned:
                raise DocumentRefAccessDeniedError()
        return [ref.citation for ref in refs]


def test_absent_refs_resolve_to_nothing() -> None:
    assert parse_document_refs(None) == ()
    assert parse_document_refs([]) == ()


def test_refs_parse_into_canonical_citations() -> None:
    (ref,) = parse_document_refs(_body((DOCUMENT_ID, VERSION_ID)))

    assert ref.citation == f"doc:{DOCUMENT_ID}:{VERSION_ID}"


def test_invalid_shape_or_uuid_is_a_client_error() -> None:
    for invalid in (
        "not-a-list",
        [["document_id", DOCUMENT_ID]],
        [{"document_id": DOCUMENT_ID}],
        [{"document_id": DOCUMENT_ID, "version_id": VERSION_ID, "extra": "x"}],
        [{"document_id": "not-a-uuid", "version_id": VERSION_ID}],
        [{"document_id": DOCUMENT_ID, "version_id": 7}],
    ):
        with pytest.raises(DocumentRefSyntaxError) as invalid_input:
            parse_document_refs(invalid)  # type: ignore[arg-type]
        assert invalid_input.value.status_code == 400


def test_duplicates_and_overflow_are_rejected() -> None:
    with pytest.raises(DocumentRefSyntaxError, match="unique"):
        parse_document_refs(_body((DOCUMENT_ID, VERSION_ID), (DOCUMENT_ID, VERSION_ID)))
    oversized = [
        {"document_id": DOCUMENT_ID, "version_id": f"{index:08x}-2222-4222-8222-222222222222"}
        for index in range(MAX_DOCUMENT_REFS + 1)
    ]
    with pytest.raises(DocumentRefSyntaxError, match="at most 8"):
        parse_document_refs(oversized)  # type: ignore[arg-type]


async def test_resolution_is_scoped_to_the_authenticated_principal() -> None:
    resolver = _Resolver()
    refs = parse_document_refs(_body((DOCUMENT_ID, VERSION_ID)))

    citations = await resolve_document_refs(scope=SCOPE, refs=refs, resolver=resolver)

    assert citations == (f"doc:{DOCUMENT_ID}:{VERSION_ID}",)
    assert resolver.calls == ["principal-1"]


async def test_unowned_version_returns_one_uniform_denial() -> None:
    resolver = _Resolver(owned=set())
    refs = parse_document_refs(_body((DOCUMENT_ID, VERSION_ID)))

    with pytest.raises(DocumentRefAccessDeniedError) as denied:
        await resolve_document_refs(scope=SCOPE, refs=refs, resolver=resolver)

    assert str(denied.value) == ACCESS_DENIED_MESSAGE
    assert denied.value.status_code == 403


async def test_missing_resolver_is_unavailable_not_denied() -> None:
    refs = parse_document_refs(_body((DOCUMENT_ID, VERSION_ID)))

    with pytest.raises(DocumentRefResolverUnavailableError) as unavailable:
        await resolve_document_refs(scope=SCOPE, refs=refs, resolver=None)

    assert unavailable.value.status_code == 501


async def test_no_resolver_call_happens_without_references() -> None:
    resolver = _Resolver()

    assert await resolve_document_refs(scope=SCOPE, refs=(), resolver=resolver) == ()
    assert resolver.calls == []


async def test_reordered_or_substituted_citations_fail_closed() -> None:
    refs = parse_document_refs(_body((DOCUMENT_ID, VERSION_ID), (DOCUMENT_ID, OTHER_VERSION_ID)))

    class _Reordering:
        async def resolve(
            self,
            *,
            principal_id: str,  # noqa: ARG002
            refs: Sequence[DocumentRef],
        ) -> Sequence[str]:
            return [ref.citation for ref in reversed(refs)]

    class _Substituting:
        async def resolve(
            self,
            *,
            principal_id: str,  # noqa: ARG002
            refs: Sequence[DocumentRef],  # noqa: ARG002
        ) -> Sequence[str]:
            return ["doc:other:other", "doc:other:other2"]

    for resolver in (_Reordering(), _Substituting()):
        with pytest.raises(DocumentRefIntegrityError):
            await resolve_document_refs(scope=SCOPE, refs=refs, resolver=resolver)


async def test_short_or_padded_resolver_results_are_denied() -> None:
    refs = parse_document_refs(_body((DOCUMENT_ID, VERSION_ID)))

    class _Short:
        async def resolve(
            self,
            *,
            principal_id: str,  # noqa: ARG002
            refs: Sequence[DocumentRef],  # noqa: ARG002
        ) -> Sequence[str]:
            return []

    class _Padded:
        async def resolve(
            self,
            *,
            principal_id: str,  # noqa: ARG002
            refs: Sequence[DocumentRef],
        ) -> Sequence[str]:
            return [*(ref.citation for ref in refs), "doc:extra:extra"]

    for resolver in (_Short(), _Padded()):
        with pytest.raises(DocumentRefAccessDeniedError):
            await resolve_document_refs(scope=SCOPE, refs=refs, resolver=resolver)
