"""Protected environment rendering preserves literals, secret refs and canary field refs."""

from __future__ import annotations

from copy import deepcopy

import pytest

from fdai_deployment_cli.aks_job_environment import (
    protected_environment_entries,
    protected_environment_sources,
)

FIELD = {"FDAI_CANARY_JOB_UID": "metadata.labels['batch.kubernetes.io/controller-uid']"}


def test_environment_sources_are_retained_with_deep_copy_isolation() -> None:
    sources = [{"configMapRef": {"name": "example-config"}}]
    result = protected_environment_sources(sources)
    assert result == sources
    result[0]["configMapRef"]["name"] = "other-config"
    assert sources == [{"configMapRef": {"name": "example-config"}}]
    assert protected_environment_sources([]) == []


@pytest.mark.parametrize("value", [None, {}, ["not-an-object"], [{1: "not-a-string-key"}]])
def test_invalid_environment_sources_preserve_error_contract(value: object) -> None:
    with pytest.raises(ValueError, match="^protected AKS Job envFrom contract is invalid$"):
        protected_environment_sources(value)


def test_mixed_environment_preserves_exact_references_order_and_inputs() -> None:
    environment = {"Z_LITERAL": "literal", "A_LITERAL": "first"}
    secrets = {"M_SECRET": "provider-object"}
    fields = dict(FIELD)
    original = deepcopy((environment, secrets, fields))
    assert protected_environment_entries(
        component="canary",
        template_name="example-canary",
        environment=environment,
        secret_environment=secrets,
        field_environment=fields,
    ) == [
        {"name": "A_LITERAL", "value": "first"},
        {
            "name": "FDAI_CANARY_JOB_UID",
            "valueFrom": {
                "fieldRef": {
                    "apiVersion": "v1",
                    "fieldPath": "metadata.labels['batch.kubernetes.io/controller-uid']",
                }
            },
        },
        {
            "name": "M_SECRET",
            "valueFrom": {"secretKeyRef": {"name": "example-canary-job", "key": "M_SECRET"}},
        },
        {"name": "Z_LITERAL", "value": "literal"},
    ]
    assert (environment, secrets, fields) == original


@pytest.mark.parametrize("component", ["canary", "analyzer"])
def test_legacy_empty_field_bindings_do_not_add_environment(component: str) -> None:
    assert (
        protected_environment_entries(
            component=component,
            template_name="example-job",
            environment={},
            secret_environment={},
            field_environment={},
        )
        == []
    )


@pytest.mark.parametrize(
    ("component", "fields"),
    [
        ("analyzer", FIELD),
        ("canary", {"FDAI_CANARY_JOB_UID": "metadata.uid"}),
        ("canary", {"UNREVIEWED_FIELD": "metadata.labels['batch.kubernetes.io/controller-uid']"}),
    ],
)
def test_unreviewed_field_references_still_fail(component: str, fields: dict[str, str]) -> None:
    with pytest.raises(
        ValueError, match="^protected AKS canary Job identity field reference is invalid$"
    ):
        protected_environment_entries(
            component=component,
            template_name="example-job",
            environment={},
            secret_environment={},
            field_environment=fields,
        )


@pytest.mark.parametrize("secret_collision", [False, True])
def test_canary_identity_cannot_collide_with_literal_or_secret_binding(
    secret_collision: bool,
) -> None:
    duplicate = {"FDAI_CANARY_JOB_UID": "other-binding"}
    with pytest.raises(
        ValueError, match="^protected AKS canary Job identity field reference is invalid$"
    ):
        protected_environment_entries(
            component="canary",
            template_name="example-job",
            environment={} if secret_collision else duplicate,
            secret_environment=duplicate if secret_collision else {},
            field_environment=FIELD,
        )
