"""Executable ownership checks for Operator API configuration groups."""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections import Counter
from dataclasses import FrozenInstanceError, fields

import pytest

from fdai.delivery.operator_api.app.config import OperatorApiConfig
from fdai.delivery.operator_api.main import (
    ConversationRouteBindings,
    GovernedRouteBindings,
    HttpSurfaceBindings,
    LifecycleBindings,
    OperatorApiComposition,
    OperatorApiRuntimeBindings,
    OperatorApiValues,
    ProjectionRouteBindings,
    ReadViewBindings,
    StreamRouteBindings,
)
from fdai.delivery.operator_api.routes.busy_input_runtime import (
    BusyInputRuntime,
    BusyInputRuntimeMetrics,
)
from fdai.delivery.operator_api.streaming.live_stream import LiveStreamConfig


def test_legacy_config_splits_values_from_stream_bindings() -> None:
    stream = LiveStreamConfig()
    config = OperatorApiConfig(
        cors_allow_origins=("https://console.example.com",),
        live_stream=stream,
    )

    composition = config.split()

    assert composition.values.cors_allow_origins == ("https://console.example.com",)
    assert composition.bindings.streams.live_stream is stream
    assert not hasattr(composition.bindings.projections, "live_stream")
    assert not hasattr(composition.values, "live_stream")
    assert not hasattr(composition.bindings.streams, "cors_allow_origins")
    with pytest.raises(FrozenInstanceError):
        composition.bindings.streams.live_stream = None  # type: ignore[misc]


def test_cross_group_invariants_fail_before_route_registration() -> None:
    class Coordinator:
        pass

    composition = OperatorApiConfig(
        busy_input_runtime=BusyInputRuntime(
            coordinator=Coordinator(),  # type: ignore[arg-type]
            metrics=BusyInputRuntimeMetrics(),
        ),
    ).split()

    with pytest.raises(ValueError, match="requires a configured chat backend"):
        composition.validate()


def test_public_split_contracts_are_additive_and_empty_by_default() -> None:
    composition = OperatorApiComposition(
        values=OperatorApiValues(),
        bindings=OperatorApiRuntimeBindings(),
    )

    composition.validate()
    assert composition.values.dev_mode is False
    assert composition.bindings.conversation.chat is None


def test_legacy_config_defensively_copies_mapping_inputs() -> None:
    profile: dict[str, object] = {"oid": "operator-a"}
    role_groups = {"Reader": "group-a"}
    evaluators: dict[str, object] = {"baseline": object()}
    config = OperatorApiConfig(
        local_cli_profile=profile,
        iam_role_group_ids=role_groups,
        what_if_evaluators=evaluators,
    )

    profile["oid"] = "operator-b"
    role_groups["Owner"] = "group-b"
    evaluators["replacement"] = object()

    assert config.local_cli_profile == {"oid": "operator-a"}
    assert config.iam_role_group_ids == {"Reader": "group-a"}
    assert tuple(config.what_if_evaluators) == ("baseline",)
    with pytest.raises(TypeError):
        config.iam_role_group_ids["Owner"] = "group-b"  # type: ignore[index]


def test_shared_capability_consumers_must_reference_one_binding() -> None:
    composition = OperatorApiComposition(
        bindings=OperatorApiRuntimeBindings(
            conversation=ConversationRouteBindings(console_action=object()),
            http=HttpSurfaceBindings(console_action=object()),
        )
    )

    with pytest.raises(
        ValueError,
        match="shared console action submitter bindings MUST reference the same object",
    ):
        composition.validate()


def test_shared_tuple_consumers_reject_configured_and_empty_mismatch() -> None:
    panel = object()
    composition = OperatorApiComposition(
        bindings=OperatorApiRuntimeBindings(
            conversation=ConversationRouteBindings(extra_panels=(panel,)),
            http=HttpSurfaceBindings(extra_panels=()),
        )
    )

    with pytest.raises(
        ValueError,
        match="shared extra panels bindings MUST reference the same object",
    ):
        composition.validate()


def test_full_legacy_composition_validates_across_binding_families() -> None:
    shared_chat = object()
    shared_history = object()
    shared_inventory = object()
    composition = OperatorApiConfig(
        live_stream=LiveStreamConfig(),
        blast_radius_graph=object(),
        inventory_graph_provider=shared_inventory,
        chat=shared_chat,
        conversation_history_store=shared_history,
        reporting=object(),
        handover_goals=object(),
        authoritative_read_proxy=object(),
    ).split()

    composition.validate()
    assert composition.bindings.streams.live_stream is not None
    assert composition.bindings.projections.blast_radius_graph is not None
    assert composition.bindings.projections.inventory_graph_provider is shared_inventory
    assert composition.bindings.read_views.reporting is not None
    assert composition.bindings.conversation.chat is shared_chat
    assert composition.bindings.governed.handover_goals is not None
    assert composition.bindings.http.authoritative_read_proxy is not None


def test_split_maps_every_legacy_field_and_only_reviewed_shared_references() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(OperatorApiConfig.split)))
    references = Counter(
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )

    assert set(references) == {field.name for field in fields(OperatorApiConfig)}
    assert {name for name, count in references.items() if count > 1} == {
        "chat",
        "chat_web_search",
        "console_action",
        "conversation_history_store",
        "conversation_progress_metrics",
        "data_sources",
        "detection_readiness_reader",
        "extra_panels",
        "inventory_graph_provider",
        "model_settings",
        "stewardship_map",
    }


def test_nested_binding_schemas_exclude_raw_authority_and_credential_fields() -> None:
    forbidden_tokens = {
        "access_token",
        "credential",
        "executor_identity",
        "provider_endpoint",
        "secret",
        "tenant_id",
        "workload_identity",
    }
    binding_types = (
        StreamRouteBindings,
        ProjectionRouteBindings,
        LifecycleBindings,
        ReadViewBindings,
        ConversationRouteBindings,
        GovernedRouteBindings,
        HttpSurfaceBindings,
    )

    field_names = {field.name for binding_type in binding_types for field in fields(binding_type)}
    assert forbidden_tokens.isdisjoint(field_names)
