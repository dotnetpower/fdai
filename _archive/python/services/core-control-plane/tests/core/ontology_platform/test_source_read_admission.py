"""Current source checks enclose every secured graph read surface, never a write path."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyInstancePathDefinition,
    TypedPathStep,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryGateway
from fdai.core.ontology_platform.source_read_admission import (
    SourceReadAdmission,
    SourceReadAdmissionError,
    admitted_source_read,
)
from fdai.shared.contracts.models import (
    CeilingRole,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.ontology.release import build_ontology_release

SCOPE = "sha256:" + "a" * 64
PURPOSE = "operations-review"
AT = datetime(2026, 10, 19, tzinfo=UTC)


def admission(**changes):
    return SourceReadAdmission(
        **{
            "principal_scope_digest": SCOPE,
            "purpose": PURPOSE,
            "source_state_digest": "sha256:" + "b" * 64,
            **changes,
        }
    )


def request(**changes):
    return ProjectionRequest(
        **{
            "caller_role": CeilingRole.OWNER,
            "declared_purposes": frozenset({PURPOSE, "audit-review"}),
            "principal_scope_digest": SCOPE,
            **changes,
        }
    )


def gateway(reader):
    declaration = OntologyObjectType(
        schema_version="1.0.0",
        name="BusinessService",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    return SecuredObjectSetQueryGateway(
        service=AsyncMock(),
        object_types={declaration.name: declaration},
        ontology_release=build_ontology_release(object_types=(declaration,)),
        evaluation_cutoff=lambda: AT,
        source_read_admission=reader,
    )


async def invoke(gate, mode, projection_request):
    selector = ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="BusinessService")
    if mode == "index":
        return await gate.scan_snapshot(
            object_type_names=("BusinessService",),
            purpose=PURPOSE,
            as_of=AT,
            candidate_limit=100,
            projection_request=projection_request,
        )
    if mode == "path":
        return await gate.materialize_instance_path(
            OntologyInstancePathDefinition(
                root_selector=selector,
                steps=(
                    TypedPathStep(link_type="depends_on", direction="outgoing", selector=selector),
                ),
                purpose=PURPOSE,
                as_of=AT,
            ),
            projection_request=projection_request,
        )
    return await gate.materialize(
        ObjectSetDefinition(selector=selector, purpose=PURPOSE, as_of=AT),
        projection_request=projection_request,
    )


def stub_read(gate, mode):
    method = {"index": "_scan_snapshot", "path": "_materialize_instance_path"}.get(
        mode, "_materialize"
    )
    operation = AsyncMock(return_value=object())
    setattr(gate, method, operation)
    return operation


@pytest.mark.parametrize("mode", ["query", "path", "index"])
async def test_every_surface_checks_current_scope_and_only_its_own_purpose_twice(mode):
    reader = AsyncMock()
    reader.authorize.return_value = admission()
    gate = gateway(reader)
    operation = stub_read(gate, mode)

    result = await invoke(gate, mode, request())

    assert result is operation.return_value
    assert reader.authorize.await_count == 2
    for call in reader.authorize.await_args_list:
        assert call.kwargs == {"principal_scope_digest": SCOPE, "purpose": PURPOSE}
    operation.assert_awaited_once()


@pytest.mark.parametrize("mode", ["query", "path", "index"])
@pytest.mark.parametrize(
    "error", [PermissionError("private source detail"), RuntimeError("private source detail")]
)
async def test_denied_or_unavailable_admission_precedes_any_graph_work(mode, error):
    reader = AsyncMock()
    reader.authorize.side_effect = error
    gate = gateway(reader)
    operation = stub_read(gate, mode)

    with pytest.raises((PermissionError, SourceReadAdmissionError)) as caught:
        await invoke(gate, mode, request())

    assert "private source detail" not in str(caught.value)
    operation.assert_not_awaited()
    reader.authorize.assert_awaited_once()


@pytest.mark.parametrize("mode", ["query", "path", "index"])
@pytest.mark.parametrize("change", ["revision", "revoke", "missing"])
async def test_changed_source_after_materialization_never_releases_graph_or_counts(mode, change):
    reader = AsyncMock()
    after = {
        "revision": admission(source_state_digest="sha256:" + "c" * 64),
        "revoke": PermissionError("source withdrawn"),
        "missing": SourceReadAdmissionError("source absent"),
    }[change]
    reader.authorize.side_effect = [admission(), after]
    gate = gateway(reader)
    operation = stub_read(gate, mode)

    with pytest.raises((PermissionError, SourceReadAdmissionError)):
        await invoke(gate, mode, request())

    operation.assert_awaited_once()
    assert reader.authorize.await_count == 2


@pytest.mark.parametrize(
    "bad_request",
    [
        request(principal_scope_digest=None),
        request(declared_purposes=frozenset({"audit-review"})),
    ],
)
async def test_missing_authenticated_scope_or_purpose_cannot_call_source_reader(bad_request):
    reader = AsyncMock()
    with pytest.raises(PermissionError):
        async with admitted_source_read(reader, request=bad_request, purpose=PURPOSE):
            pytest.fail("read cannot begin")
    reader.authorize.assert_not_awaited()


@pytest.mark.parametrize(
    "result",
    [
        None,
        admission(principal_scope_digest="sha256:" + "d" * 64),
        admission(purpose="audit-review"),
    ],
)
async def test_spliced_or_missing_source_proof_fails_closed(result):
    reader = AsyncMock()
    reader.authorize.return_value = result
    with pytest.raises(SourceReadAdmissionError, match="does not match read"):
        async with admitted_source_read(reader, request=request(), purpose=PURPOSE):
            pytest.fail("read cannot begin")


async def test_cancellation_does_not_become_provider_unavailable():
    reader = AsyncMock()
    reader.authorize.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        async with admitted_source_read(reader, request=request(), purpose=PURPOSE):
            pytest.fail("cancelled read cannot begin")


async def test_failed_graph_read_does_not_retry_source_or_release_partial_data():
    reader = AsyncMock()
    reader.authorize.return_value = admission()
    with pytest.raises(RuntimeError, match="graph unavailable"):
        async with admitted_source_read(reader, request=request(), purpose=PURPOSE):
            raise RuntimeError("graph unavailable")
    reader.authorize.assert_awaited_once()


@pytest.mark.parametrize("field", ["principal_scope_digest", "source_state_digest"])
def test_source_admission_requires_exact_canonical_commitments(field):
    with pytest.raises(ValueError, match="canonical SHA-256"):
        admission(**{field: "unobserved:review-only"})


def test_source_admission_and_property_review_and_preflight_hardening() -> None:
    from fdai.core.conversation.conversation_preflight_validation import bounded_context
    from fdai.core.ontology_platform.models import (
        ObjectPredicate,
        ObjectSelector,
        ObjectSelectorKind,
        ObjectTraversal,
    )
    from fdai.core.ontology_platform.query_instance_paths import instance_path_row
    from fdai.core.ontology_platform.query_manifest import ReviewedPropertyRead
    from fdai.core.ontology_platform.query_property_review import reviewed_property_paths

    # D13: whitespace purpose rejected in SourceReadAdmission
    with pytest.raises(ValueError, match="bounded purpose"):
        admission(purpose="   ")

    # D16: control-char selector/predicate and duplicate link_types rejected
    with pytest.raises(ValueError, match="non-empty and trimmed"):
        ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource\x00")
    with pytest.raises(ValueError, match="non-empty and trimmed"):
        ObjectPredicate(property="status\nname", equals="ready")
    with pytest.raises(ValueError, match="unique"):
        ObjectTraversal(link_types=("CONTAINS", "CONTAINS"))

    # D19: reviewed_property_paths unions resource types across multiple ReviewedPropertyRead items
    paths = reviewed_property_paths(
        (
            ReviewedPropertyRead(
                semantic_id="s1",
                value_type="string",
                unit=None,
                max_age_seconds=60,
                paths=(("Microsoft.Compute/virtualMachines", "provisioningState"),),
            ),
            ReviewedPropertyRead(
                semantic_id="s2",
                value_type="string",
                unit=None,
                max_age_seconds=60,
                paths=(("Microsoft.Storage/storageAccounts", "provisioningState"),),
            ),
        )
    )
    assert paths["properties.properties.provisioningState"] == frozenset(
        {
            "Microsoft.Compute/virtualMachines",
            "Microsoft.Storage/storageAccounts",
        }
    )

    # D20: empty instance_path_row raises ValueError
    with pytest.raises(ValueError, match="at least one object"):
        instance_path_row(())

    # D23: bounded_context skips empty/whitespace turns without dropping earlier turns
    assert bounded_context(("turn-1", "   ", "")) == ("turn-1",)
    with pytest.raises(TypeError, match="sequence of strings"):
        bounded_context("raw-string")
