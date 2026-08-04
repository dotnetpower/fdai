"""Kubernetes custom owner evidence semantics tests."""

from __future__ import annotations

from fdai.delivery.kubernetes.owners import (
    CustomOwnerQuery,
    custom_owner_queries,
    project_custom_owner,
)


def test_custom_owner_queries_are_deduplicated_bounded_and_uid_grounded() -> None:
    owner = {
        "api_version": "database.example.io/v1",
        "kind": "Database",
        "name": "catalog",
        "uid": "owner-uid",
    }
    queries, omitted = custom_owner_queries(
        [
            {"owner_reference_projection_complete": True, "owner_references": [owner]},
            {"owner_reference_projection_complete": True, "owner_references": [owner]},
            {
                "owner_reference_projection_complete": True,
                "owner_references": [{**owner, "name": "orders", "uid": "orders-uid"}],
            },
        ],
        max_owners=1,
    )

    assert queries == (CustomOwnerQuery("database.database.example.io/catalog", "owner-uid"),)
    assert omitted == 1


def test_custom_owner_projection_requires_exact_immutable_identity() -> None:
    query = CustomOwnerQuery("database.database.example.io/catalog", "owner-uid")

    projection = project_custom_owner(
        _payload(),
        namespace="example-app",
        query=query,
    )

    assert projection == {
        "api_version": "database.example.io/v1",
        "kind": "Database",
        "name": "catalog",
        "namespace": "example-app",
        "uid": "owner-uid",
        "custom_resource": True,
        "resource_version": "7",
        "generation": 3,
        "deleting": False,
        "conditions": [{"type": "Ready", "status": "False", "reason": "Reconciling"}],
    }
    assert "spec" not in projection
    assert "image" not in projection


def test_custom_owner_projection_rejects_recreated_or_cross_namespace_owner() -> None:
    query = CustomOwnerQuery("database.database.example.io/catalog", "owner-uid")
    recreated = _payload()
    recreated["metadata"]["uid"] = "replacement-uid"  # type: ignore[index]
    cross_namespace = _payload()
    cross_namespace["metadata"]["namespace"] = "other-app"  # type: ignore[index]

    assert project_custom_owner(recreated, namespace="example-app", query=query) is None
    assert project_custom_owner(cross_namespace, namespace="example-app", query=query) is None


def test_custom_owner_projection_does_not_interpret_arbitrary_spec_fields() -> None:
    query = CustomOwnerQuery("database.database.example.io/catalog", "owner-uid")
    payload = _payload()
    payload["spec"] = {
        "runAsUser": -1,
        "effect": "Sometimes",
        "updateStrategy": "ReplaceImmediately",
    }

    projection = project_custom_owner(payload, namespace="example-app", query=query)

    assert projection is not None
    assert "spec" not in projection
    assert "configuration" not in projection


def test_custom_owner_queries_reject_builtin_malformed_or_uidless_references() -> None:
    queries, omitted = custom_owner_queries(
        [
            {
                "owner_reference_projection_complete": True,
                "owner_references": [
                    {
                        "api_version": "apps/v1",
                        "kind": "Deployment",
                        "name": "api",
                        "uid": "deployment-uid",
                    },
                    {
                        "api_version": "database.example.io/v1",
                        "kind": "Database",
                        "name": "not valid",
                        "uid": "owner-uid",
                    },
                    {
                        "api_version": "database.example.io/v1",
                        "kind": "Database",
                        "name": "catalog",
                    },
                ],
            }
        ],
        max_owners=8,
    )

    assert queries == ()
    assert omitted == 3


def test_custom_owner_queries_count_incomplete_projection_as_omitted() -> None:
    queries, omitted = custom_owner_queries(
        [
            {
                "owner_reference_projection_complete": False,
                "owner_references": [],
            }
        ],
        max_owners=8,
    )

    assert queries == ()
    assert omitted == 1


def _payload() -> dict[str, object]:
    return {
        "apiVersion": "database.example.io/v1",
        "kind": "Database",
        "metadata": {
            "name": "catalog",
            "namespace": "example-app",
            "uid": "owner-uid",
            "resourceVersion": "7",
            "generation": 3,
        },
        "spec": {"image": "must-not-project", "password": "must-not-project"},
        "status": {"conditions": [{"type": "Ready", "status": "False", "reason": "Reconciling"}]},
    }
