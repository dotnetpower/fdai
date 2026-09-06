"""Principal-scoped governed document FunctionType tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.governed_document_queries import (
    GOVERNED_DOCUMENT_FUNCTION_NAME,
    GOVERNED_DOCUMENT_MEASURE_CONCEPT,
    GovernedDocumentCollection,
    GovernedDocumentExcerpt,
    governed_document_function,
    governed_document_function_type,
)
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release

NOW = datetime(2026, 9, 6, 5, 0, tzinfo=UTC)


class _Reader:
    def __init__(self, result: GovernedDocumentCollection) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        *,
        query: str,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
        limit: int,
    ) -> GovernedDocumentCollection:
        self.calls.append(
            {
                "query": query,
                "principal_ref": principal_ref,
                "principal_role": principal_role,
                "principal_groups": principal_groups,
                "purpose": purpose,
                "limit": limit,
            }
        )
        return self.result


def _collection(
    *,
    excerpts: tuple[GovernedDocumentExcerpt, ...] = (),
    complete: bool = True,
    limitation: str | None = None,
) -> GovernedDocumentCollection:
    return GovernedDocumentCollection(
        excerpts=excerpts,
        observed_at=NOW,
        complete=complete,
        limitation=limitation,
        index_generation="document-index:sha256:" + ("1" * 64),
        access_scope_digest="sha256:" + ("2" * 64),
        retrieval_mode="hybrid",
    )


def _excerpt() -> GovernedDocumentExcerpt:
    return GovernedDocumentExcerpt(
        evidence_ref="document:sha256:" + ("3" * 64),
        document_revision="version:00000000-0000-0000-0000-000000000001:sha256:" + ("4" * 64),
        source_name="recovery-runbook.md",
        source_ref="doc:00000000-0000-0000-0000-000000000001:chunk-1",
        locator="section:recovery/paragraph:2",
        chunk_id="chunk-1",
        text="Verify the health probe before restarting the workload.",
        content_digest="sha256:" + ("5" * 64),
        score=0.91,
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("source_name", "", "bounded"),
        ("text", "", "text"),
        ("content_digest", "sha256:bad", "digest"),
        ("content_digest", "sha256:" + ("z" * 64), "digest"),
        ("evidence_ref", "document:invalid", "evidence ref"),
        ("document_revision", "version:invalid", "revision"),
        ("score", float("nan"), "score"),
        ("instruction_authority", True, "instruction authority"),
    ),
)
def test_excerpt_rejects_invalid_identity_and_content(
    field: str,
    value: object,
    message: str,
) -> None:
    values = {
        "evidence_ref": "document:sha256:" + ("3" * 64),
        "document_revision": ("version:00000000-0000-0000-0000-000000000001:sha256:" + ("4" * 64)),
        "source_name": "recovery-runbook.md",
        "source_ref": "document://source",
        "locator": "section:recovery",
        "chunk_id": "chunk-1",
        "text": "Verify the health probe.",
        "content_digest": "sha256:" + ("5" * 64),
        "score": 0.91,
        "instruction_authority": False,
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        GovernedDocumentExcerpt(**values)  # type: ignore[arg-type]


def test_collection_rejects_invalid_bounds_order_and_provenance() -> None:
    excerpt = _excerpt()
    lower_score = replace(
        excerpt,
        evidence_ref="document:sha256:" + ("7" * 64),
        chunk_id="chunk-2",
        score=0.1,
    )
    higher_score = replace(
        excerpt,
        evidence_ref="document:sha256:" + ("8" * 64),
        chunk_id="chunk-3",
        score=0.9,
    )
    base = {
        "excerpts": (),
        "observed_at": NOW,
        "complete": True,
        "limitation": None,
        "index_generation": "document-index:sha256:" + ("1" * 64),
        "access_scope_digest": "sha256:" + ("2" * 64),
        "retrieval_mode": "hybrid",
    }
    invalid = (
        ({**base, "excerpts": (excerpt,) * 9}, "excerpt bound"),
        ({**base, "excerpts": (lower_score, higher_score)}, "ordered"),
        ({**base, "observed_at": NOW.replace(tzinfo=None)}, "timezone-aware"),
        ({**base, "limitation": "unexpected"}, "inconsistent"),
        ({**base, "index_generation": ""}, "index_generation"),
        ({**base, "access_scope_digest": "invalid"}, "SHA-256"),
        ({**base, "access_scope_digest": "sha256:" + ("z" * 64)}, "SHA-256"),
    )

    for values, message in invalid:
        with pytest.raises(ValueError, match=message):
            GovernedDocumentCollection(**values)  # type: ignore[arg-type]


async def _invoke(
    reader: _Reader,
    *,
    arguments: dict[str, object] | None = None,
    principal_ref: str | None = "operator-a",
) -> dict[str, object]:
    declaration = governed_document_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(
        declaration,
        governed_document_function(release, reader=reader),
    )
    result = await registry.invoke(
        GOVERNED_DOCUMENT_FUNCTION_NAME,
        arguments
        or {
            "query": "What does the recovery runbook require?",
            "evidence_mode": "explicit",
        },
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
            principal_ref=principal_ref,
            principal_scope_digest="sha256:" + ("6" * 64),
        ),
    )
    assert isinstance(result, dict)
    return result


async def _evaluate(
    reader: _Reader,
    *,
    arguments: dict[str, object],
    purposes: tuple[str, ...] = ("operations-review",),
    principal_ref: str | None = "operator-a",
) -> object:
    declaration = governed_document_function_type()
    release = build_ontology_release(function_types=(declaration,))
    function = governed_document_function(release, reader=reader)
    return await function(
        arguments,
        FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=purposes,
            principal_ref=principal_ref,
            principal_scope_digest="sha256:" + ("6" * 64),
        ),
    )


def test_governed_document_function_declares_bounded_read_contract() -> None:
    declaration = governed_document_function_type()

    assert declaration.name == GOVERNED_DOCUMENT_FUNCTION_NAME
    assert declaration.output_schema["x-fdai-measure-concepts"] == [
        GOVERNED_DOCUMENT_MEASURE_CONCEPT
    ]
    assert declaration.required_role is CeilingRole.READER
    assert declaration.network_allowed is False
    assert declaration.credentials_allowed is False


async def test_governed_document_function_projects_exact_citation_fields() -> None:
    reader = _Reader(_collection(excerpts=(_excerpt(),)))

    result = await _invoke(reader)

    assert result["complete"] is True
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["excerpt_count"] == 1
    assert rows[0]["values"]["instruction_authority"] is False
    assert rows[1]["values"] == {
        "access_scope_digest": "sha256:" + ("2" * 64),
        "chunk_id": "chunk-1",
        "content_digest": "sha256:" + ("5" * 64),
        "document_revision": ("version:00000000-0000-0000-0000-000000000001:sha256:" + ("4" * 64)),
        "evidence_ref": "document:sha256:" + ("3" * 64),
        "execution_authority": False,
        "index_generation": "document-index:sha256:" + ("1" * 64),
        "instruction_authority": False,
        "locator": "section:recovery/paragraph:2",
        "record_kind": "excerpt",
        "retrieval_mode": "hybrid",
        "score": 0.91,
        "source_name": "recovery-runbook.md",
        "source_ref": "doc:00000000-0000-0000-0000-000000000001:chunk-1",
        "text": "Verify the health probe before restarting the workload.",
    }
    assert reader.calls == [
        {
            "query": "What does the recovery runbook require?",
            "principal_ref": "operator-a",
            "principal_role": CeilingRole.READER,
            "principal_groups": frozenset(),
            "purpose": "operations-review",
            "limit": 8,
        }
    ]


async def test_governed_document_function_preserves_incomplete_search() -> None:
    result = await _invoke(
        _Reader(
            _collection(
                excerpts=(_excerpt(),),
                complete=False,
                limitation="candidate_limit_reached",
            )
        )
    )

    assert result["complete"] is False
    assert result["truncation_reason"] == "candidate_limit_reached"
    assert result["rows"][0]["values"]["count_posture"] == "minimum"


async def test_governed_document_function_requires_principal_context() -> None:
    with pytest.raises(
        PermissionError,
        match="governed document search requires a principal identity",
    ):
        await _invoke(_Reader(_collection()), principal_ref=None)


async def test_governed_document_function_rejects_wrong_purpose() -> None:
    with pytest.raises(PermissionError, match="purpose"):
        await _evaluate(
            _Reader(_collection()),
            arguments={"query": "runbook", "evidence_mode": "explicit"},
            purposes=("incident-investigation",),
        )


@pytest.mark.parametrize(
    "arguments",
    (
        {"query": "", "evidence_mode": "explicit"},
        {"query": "runbook", "evidence_mode": "none"},
        {"query": "runbook", "evidence_mode": "explicit", "limit": True},
        {"query": "runbook", "evidence_mode": "explicit", "limit": 9},
    ),
)
async def test_governed_document_function_rejects_invalid_arguments(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        await _invoke(_Reader(_collection()), arguments=arguments)


@pytest.mark.parametrize(
    "arguments",
    (
        {"query": "", "evidence_mode": "explicit"},
        {"query": "runbook", "evidence_mode": "none"},
        {"query": "runbook", "evidence_mode": "explicit", "limit": True},
    ),
)
async def test_governed_document_evaluator_rejects_invalid_arguments(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        await _evaluate(_Reader(_collection()), arguments=arguments)


async def test_governed_document_evaluator_rejects_reader_limit_overflow() -> None:
    first = _excerpt()
    second = replace(
        first,
        evidence_ref="document:sha256:" + ("7" * 64),
        chunk_id="chunk-2",
    )

    with pytest.raises(ValueError, match="exceeded"):
        await _evaluate(
            _Reader(_collection(excerpts=(first, second))),
            arguments={"query": "runbook", "evidence_mode": "explicit", "limit": 1},
        )
