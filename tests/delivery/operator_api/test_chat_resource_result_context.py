from fdai.delivery.operator_api.projections.conversation.terminal import (
    ambiguous_resource_candidates,
    ordinal_inventory_arguments,
    parse_resource_result_context,
    response_resource_result_context,
)


def _view_context(*, freshness: str = "fresh") -> dict[str, object]:
    return {
        "_tool_evidence": {
            "tool": "query_inventory",
            "authority": "server_inventory_graph",
            "result": {
                "status": "matched",
                "source": "azure-resource-graph",
                "snapshot_at": "2026-07-20T10:00:00Z",
                "freshness": freshness,
                "matched_count": 2,
                "truncated": False,
                "query": {
                    "source": "current",
                    "kind": "list",
                    "predicates": [],
                    "scope": "subscription",
                },
                "resources": [
                    {
                        "id": "/subscriptions/example/resourceGroups/rg-example/providers/a/one",
                        "name": "app-one",
                        "type": "compute.app",
                        "resource_group": "rg-example",
                        "location": "koreacentral",
                        "status": "running",
                    },
                    {
                        "id": "/subscriptions/example/resourceGroups/rg-example/providers/a/two",
                        "name": "app-two",
                        "type": "compute.app",
                        "resource_group": "rg-example",
                        "location": "koreacentral",
                        "status": "stopped",
                    },
                ],
            },
        }
    }


def test_verified_fresh_inventory_projects_bounded_replay_context() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")

    assert context is not None
    assert context["schema_version"] == 1
    assert context["scope"] == "subscription"
    assert len(context["query_digest"]) == 64
    assert context["resources"][1] == {
        "name": "app-two",
        "resource_type": "compute.app",
        "resource_group": "rg-example",
        "location": "koreacentral",
        "status": "stopped",
    }
    assert "subscriptions" not in str(context)
    assert parse_resource_result_context(context) == context


def test_unverified_or_stale_inventory_does_not_create_replay_context() -> None:
    assert (
        response_resource_result_context(_view_context(), verification_status="unverified") is None
    )
    assert (
        response_resource_result_context(
            _view_context(freshness="stale"), verification_status="verified"
        )
        is None
    )


def test_replay_context_rejects_partial_or_unknown_shapes() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")
    assert context is not None

    assert parse_resource_result_context({**context, "schema_version": 2}) is None
    malformed = {**context, "resources": [context["resources"][0], {}]}
    assert parse_resource_result_context(malformed) is None


def test_projection_marks_omitted_resource_rows_as_truncated() -> None:
    view_context = _view_context()
    tool = view_context["_tool_evidence"]
    assert isinstance(tool, dict)
    result = tool["result"]
    assert isinstance(result, dict)
    result["matched_count"] = None
    result["resources"] = [
        {
            "name": f"app-{index}",
            "type": "compute.app",
            "resource_group": "rg-example",
        }
        for index in range(41)
    ]

    context = response_resource_result_context(view_context, verification_status="verified")

    assert context is not None
    assert len(context["resources"]) == 40
    assert context["truncated"] is True


def test_projection_marks_malformed_resource_omission_as_truncated() -> None:
    view_context = _view_context()
    tool = view_context["_tool_evidence"]
    assert isinstance(tool, dict)
    result = tool["result"]
    assert isinstance(result, dict)
    result["matched_count"] = None
    result["resources"] = [*result["resources"], {"name": "missing-type"}]

    context = response_resource_result_context(view_context, verification_status="verified")

    assert context is not None
    assert len(context["resources"]) == 2
    assert context["truncated"] is True


def test_ordinal_query_reselects_second_resource_with_exact_predicates() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")

    arguments, reason = ordinal_inventory_arguments(context)

    assert reason is None
    assert arguments is not None
    assert arguments["require_fresh"] is True
    assert arguments["predicates"] == [
        {"field": "name", "operator": "eq", "value": "app-two"},
        {"field": "resource_type", "operator": "eq", "value": "compute.app"},
        {"field": "resource_group", "operator": "eq", "value": "rg-example"},
    ]


def test_ordinal_and_ambiguity_reject_truncated_result_set() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")
    assert context is not None
    context["truncated"] = True

    assert ordinal_inventory_arguments(context) == (None, "prior_result_set_truncated")
    assert ambiguous_resource_candidates(context) == ((), "prior_result_set_truncated")


def test_ambiguity_returns_only_equal_name_candidates() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")
    assert context is not None
    context["resources"] = [
        {
            "name": "shared-app",
            "resource_type": "compute.app",
            "resource_group": "rg-one",
        },
        {
            "name": "SHARED-APP",
            "resource_type": "compute.app",
            "resource_group": "rg-two",
        },
        {"name": "unique-app", "resource_type": "compute.app"},
    ]

    candidates, reason = ambiguous_resource_candidates(context)

    assert reason is None
    assert [candidate["resource_group"] for candidate in candidates] == ["rg-one", "rg-two"]


def test_ambiguity_deduplicates_resource_identity_and_orders_candidates() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")
    assert context is not None
    context["resources"] = [
        {
            "name": "shared-app",
            "resource_type": "compute.app",
            "resource_group": "rg-two",
        },
        {
            "name": "SHARED-APP",
            "resource_type": "compute.app",
            "resource_group": "rg-one",
        },
        {
            "name": "shared-app",
            "resource_type": "compute.app",
            "resource_group": "rg-two",
        },
    ]

    candidates, reason = ambiguous_resource_candidates(context)

    assert reason is None
    assert [candidate["resource_group"] for candidate in candidates] == ["rg-one", "rg-two"]


def test_ambiguity_rejects_conflicting_duplicate_identity() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")
    assert context is not None
    context["resources"] = [
        {
            "name": "shared-app",
            "resource_type": "compute.app",
            "resource_group": "rg-one",
            "status": "running",
        },
        {
            "name": "SHARED-APP",
            "resource_type": "COMPUTE.APP",
            "resource_group": "RG-ONE",
            "status": "stopped",
        },
    ]

    assert ambiguous_resource_candidates(context) == (
        (),
        "ambiguous_candidate_identity_conflict",
    )


def test_ambiguity_groups_nfkc_equivalent_names() -> None:
    context = response_resource_result_context(_view_context(), verification_status="verified")
    assert context is not None
    context["resources"] = [
        {
            "name": "café-app",
            "resource_type": "compute.app",
            "resource_group": "rg-one",
        },
        {
            "name": "cafe\u0301-app",
            "resource_type": "compute.app",
            "resource_group": "rg-two",
        },
    ]

    candidates, reason = ambiguous_resource_candidates(context)

    assert reason is None
    assert len(candidates) == 2
