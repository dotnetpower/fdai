"""Readable conversation rows for observed model deployments."""

from __future__ import annotations

from fdai_operator_service.families.conversation.presentation_rows import (
    ordered_columns,
    readable_row,
)


def test_model_deployment_summary_is_readable_without_raw_provider_bags() -> None:
    row = readable_row(
        {
            "id": "deployment-1",
            "object_type": "Resource",
            "properties": {
                "name": "gpt-example",
                "type": "llm-model-deployment",
                "properties": {
                    "model_name": "gpt-5.4",
                    "model_version": "2026-09-01",
                    "model_format": "OpenAI",
                    "provisioning_state": "Succeeded",
                    "sku_name": "GlobalStandard",
                    "capacity_units": 50,
                    "current_capacity_units": 40,
                    "capacity_transitioning": True,
                    "capacity_tpm": 50_000,
                    "capacity_tpm_source": "properties.rateLimits",
                    "properties": {"provider_internal": "not-presented"},
                },
            },
        }
    )

    assert row == {
        "id": "deployment-1",
        "object_type": "Resource",
        "name": "gpt-example",
        "provisioning_state": "Succeeded",
        "model_name": "gpt-5.4",
        "model_version": "2026-09-01",
        "model_format": "OpenAI",
        "sku_name": "GlobalStandard",
        "capacity_units": 50,
        "current_capacity_units": 40,
        "capacity_transitioning": True,
        "capacity_tpm": 50_000,
        "capacity_tpm_source": "properties.rateLimits",
        "type": "llm-model-deployment",
    }
    assert ordered_columns(tuple(row))[:12] == [
        "name",
        "provisioning_state",
        "model_name",
        "model_version",
        "model_format",
        "sku_name",
        "capacity_units",
        "current_capacity_units",
        "capacity_transitioning",
        "capacity_tpm",
        "capacity_tpm_source",
        "type",
    ]


def test_an_aggregate_group_keeps_its_group_fields_as_leading_columns() -> None:
    first = readable_row(
        {
            "group": {"resource_type": "Microsoft.Network/networkSecurityGroups"},
            "operation": "count",
            "value": 5,
        }
    )
    second = readable_row(
        {"group": {"resource_type": "Microsoft.KeyVault/vaults"}, "operation": "count", "value": 1}
    )

    assert first["resource_type"] == "Microsoft.Network/networkSecurityGroups"
    assert "group" not in first
    assert ordered_columns(list(first)) == ["resource_type", "operation", "value"]
    assert second["resource_type"] == "Microsoft.KeyVault/vaults"


def test_group_values_are_redacted_and_never_overwrite_the_row_own_fields() -> None:
    row = readable_row(
        {
            "group": {"resource_id": "/subscriptions/00000000/resourceGroups/rg", "value": "x"},
            "operation": "count",
            "value": 3,
        }
    )

    assert row["resource_id"] == "<redacted>"
    assert row["value"] == 3


def test_an_ungrouped_aggregate_has_no_group_column() -> None:
    row = readable_row({"group": {}, "operation": "count", "value": 25})

    assert row == {"operation": "count", "value": 25}
    assert ordered_columns(list(row)) == ["operation", "value"]


async def test_password_and_api_key_suffixes_are_redacted_and_handle_refs_deduplicate() -> None:
    from datetime import UTC, datetime, timedelta

    import pytest
    from fdai_operator_service.families.conversation.result_handles import latest_result_handle_refs
    from fdai_service_contracts import ResultHandleRef

    row = readable_row(
        {"name": "vm-1", "admin_password": "secret-password", "service_api_key": "k"}
    )
    assert row["admin_password"] == "<redacted>"
    assert row["service_api_key"] == "<redacted>"

    now = datetime(2026, 9, 27, tzinfo=UTC)
    ref = ResultHandleRef(
        handle_ref="OpaqueHandleRef0123456789abcdefABCDEF",
        key_version="v1",
        issued_at=now,
        expires_at=now + timedelta(minutes=15),
    )

    class _Store:
        async def latest_result_handle_refs(
            self, *, principal_id: str, session_id: str, limit: int = 4
        ) -> tuple[ResultHandleRef, ...]:
            del principal_id, session_id, limit
            return (ref, ref)

    assert await latest_result_handle_refs(
        _Store(), principal_id="p1", session_id="s1", limit=2
    ) == (ref,)
    assert await latest_result_handle_refs(_Store(), principal_id="  ", session_id="s1") == ()
    with pytest.raises(ValueError, match="limit MUST be"):
        await latest_result_handle_refs(_Store(), principal_id="p1", session_id="s1", limit=0)


def test_rounds_17_to_20_operator_presentation_and_progress_hardening() -> None:
    from datetime import UTC, datetime

    import pytest
    from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError
    from fdai_operator_service.families.conversation.presentation_artifact_v2 import (
        compile_presentation_artifact_v2,
    )
    from fdai_operator_service.families.conversation.presentation_artifact_v3 import (
        assemble_presentation_artifact_v3,
        verify_presentation_artifact_v3,
    )
    from fdai_operator_service.families.conversation.semantic_progress_relay import (
        SemanticProgressRelay,
    )
    from fdai_operator_service.families.conversation.subscription_scope_presentation import (
        subscription_scope_artifact,
    )
    from fdai_operator_service.families.conversation.user_context import _moment, _text

    # D49 & D50: compile_presentation_artifact_v2 rejects whitespace-only evidence_refs
    assert (
        compile_presentation_artifact_v2(
            semantic={"evidence_refs": ["   "]},
            technical_details={
                "presentation_context": {"operation": "select", "output_shape": "resource_list"},
                "outputs": [{"rows": []}],
            },
            locale="en",
        )
        is None
    )

    # D51: boolean progress_sequence rejected in SemanticProgressRelay
    relay = SemanticProgressRelay()
    with pytest.raises(ValueError, match="non-negative integer"):
        relay.after("req-1", True)  # type: ignore[arg-type]

    # D53: assemble_presentation_artifact_v3 normalizes and validates evidence_refs
    artifact = assemble_presentation_artifact_v3(
        layout="operational_brief",
        blocks=[{"slot_id": "overview", "kind": "summary", "title": "T", "data": {}}],
        evidence_refs=[" ref-1 ", "ref-1", "   "],
        locale="en",
        input_kinds=("verified_semantic_result",),
    )
    assert artifact["evidence_refs"] == ["ref-1"]
    verify_presentation_artifact_v3(artifact)
    with pytest.raises(ValueError, match="missing"):
        verify_presentation_artifact_v3({**artifact, "evidence_refs": ["   "]})

    # D58: subscription_scope_artifact rejects non-ISO observed_at
    assert (
        subscription_scope_artifact(
            output={
                "source_complete": True,
                "rows": (
                    {
                        "values": {
                            "execution_authority": False,
                            "display_name": "Sub",
                            "state": "Enabled",
                            "masked_subscription_id": "0000...1111",
                            "observed_at": "not-a-timestamp",
                            "evidence_digest": "sha256:" + "a" * 64,
                        }
                    },
                ),
            },
            evidence_refs=["ref-1"],
            locale="en",
            verified=True,
        )
        is None
    )

    # D60: user_context _text rejects whitespace-only and _moment rejects naive datetime
    with pytest.raises(ConversationBoundaryError):
        _text({"field": "   "}, "field")
    with pytest.raises(ConversationBoundaryError):
        _moment({"ts": datetime(2026, 9, 27)}, "ts")
    assert _moment({"ts": datetime(2026, 9, 27, tzinfo=UTC)}, "ts").startswith("2026-09-27")

    # E56 & E57: inline_images_present accepts tuple and receipt writer validates DSN
    from fdai_operator_service.families.conversation.inline_images import inline_images_present
    from fdai_operator_service.families.conversation.semantic_authentication_receipts import (
        PostgresAuthenticationReceiptWriter,
    )

    assert inline_images_present({"images": ()}) is False
    assert inline_images_present({"images": ("img-1",)}) is True
    with pytest.raises(ValueError, match="non-empty DSN"):
        PostgresAuthenticationReceiptWriter(dsn="   ")

    # F106-F120: Operator channel edge, document refs, and document export guards
    from types import MappingProxyType
    from uuid import uuid4

    from fdai_operator_service.families.conversation.channel_edge.models import (
        ChannelDeliveryError,
    )
    from fdai_operator_service.families.conversation.channel_edge.renderers import _chunks
    from fdai_operator_service.families.conversation.document_export import (
        MaterializedConversationDocument,
    )
    from fdai_operator_service.families.conversation.document_refs import parse_document_refs

    with pytest.raises(ValueError, match="invalid"):
        ChannelDeliveryError("err", code="   ", acknowledgement_ambiguous=False)
    with pytest.raises(ValueError, match="positive integer"):
        _chunks("hello", True)
    doc_id, ver_id = str(uuid4()), str(uuid4())
    parsed_refs = parse_document_refs(
        (MappingProxyType({"document_id": doc_id, "version_id": ver_id}),)  # type: ignore[arg-type]
    )
    assert len(parsed_refs) == 1
    with pytest.raises(ValueError, match="non-empty"):
        MaterializedConversationDocument(
            source_request_id="   ",
            markdown="md",
            report={},
            expected_rows=1,
            included_rows=1,
            sha256="a" * 64,
        )
