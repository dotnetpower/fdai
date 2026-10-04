from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli import cli
from fdai_deployment_cli.operational_evidence_verifier_input import (
    apply_operational_evidence_verifier_input,
    load_operational_evidence_verifier_input,
)
from fdai_deployment_cli.standalone_operational_evidence import (
    aks_operational_evidence_verifier_workload,
)


def _guid(last: int) -> str:
    return "-".join(
        (
            "10000000",
            "2000",
            "3000",
            "4000",
            f"{last:012x}",
        )
    )


def _digest(marker: str) -> str:
    return marker * 64


def _scope(name: str) -> str:
    return (
        "/subscriptions/"
        + _guid(80)
        + "/resourceGroups/rg-fdai-dev-test/providers/FDAI.Test/"
        + name
    )


def _input() -> dict[str, object]:
    verifier_scope = _scope("verifier")
    return {
        "schema_version": "fdai.operational-evidence-verifier-deployment-input.v1",
        "trust_registry_path": "config/operational-evidence-trust-registry.json",
        "trust_registry_pin": _digest("a"),
        "grant_registry_path": "/app/config/operational-evidence-grants.json",
        "grant_registry_pin": _digest("b"),
        "anchors": {
            "schema_version": "1.0.0",
            "venue": "deployed",
            "anchors": [
                {
                    "anchor_id": "anchor:operational-evidence-verifier",
                    "principal_id": _guid(1),
                    "evidence_class": "live",
                },
                {
                    "anchor_id": "anchor:core-runtime",
                    "principal_id": _guid(2),
                    "evidence_class": "live",
                },
            ],
        },
        "caller_token_issuer": "https://issuer.fdai.invalid/",
        "caller_token_audience": "api://fdai-operational-evidence-verifier",
        "caller_token_jwks": {"keys": [{"kty": "RSA", "kid": "fdai-verifier"}]},
        "role_readback_scopes": [verifier_scope],
        "allowed_role_scopes": {
            "AcrPull": [verifier_scope],
            "Key Vault Secrets User": [verifier_scope],
            "Monitoring Reader": [verifier_scope],
        },
        "vertical_executor_principal_ids": [_guid(3)],
        "writer_members": ["fdai_operational_evidence_verifier"],
        "dev_gateway_executor_principal_id": _guid(4),
        "verifier_database_role": "fdai_operational_evidence_verifier",
    }


def _write(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_omitted_input_leaves_values_byte_unchanged() -> None:
    values: dict[str, object] = {"env": "dev", "region": "koreacentral"}

    apply_operational_evidence_verifier_input(values, None)

    assert values == {"env": "dev", "region": "koreacentral"}


def test_valid_input_enables_terraform_and_renders_workload(tmp_path: Path) -> None:
    profile = load_operational_evidence_verifier_input(_write(tmp_path / "verifier.json", _input()))
    values: dict[str, object] = {"env": "dev"}

    apply_operational_evidence_verifier_input(values, profile)

    assert values["enable_operational_evidence_verifier"] is True
    binding = values["operational_evidence_verifier"]
    assert isinstance(binding, dict)
    assert binding["enabled"] is True
    assert binding["trust_registry_pin"] == _digest("a")
    assert json.loads(str(binding["anchors_json"]))["venue"] == "deployed"
    assert json.loads(str(binding["writer_members_json"])) == ["fdai_operational_evidence_verifier"]

    workload = aks_operational_evidence_verifier_workload(
        refs={"core-control-plane": "registry.invalid/fdai/core@sha256:" + _digest("c")},
        verifier_identity={
            "resource_id": "/identities/verifier",
            "client_id": _guid(10),
            "principal_id": _guid(11),
        },
        core_identity={
            "resource_id": "/identities/core",
            "client_id": _guid(20),
            "principal_id": _guid(21),
        },
        executor_identity={
            "resource_id": "/identities/executor",
            "client_id": _guid(30),
            "principal_id": _guid(31),
        },
        deploy_runner_principal=_guid(40),
        application_values=values,
        postgres_fqdn="postgres.fdai.invalid",
        postgres_database="fdai",
    )

    assert workload is not None
    assert workload["component"] == "operational-evidence-verifier"
    assert workload["environment"]["FDAI_DATABASE_ROLE"] == ("fdai_operational_evidence_verifier")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.pop("trust_registry_pin"), "fields"),
        (lambda value: value.update({"unexpected": True}), "fields"),
        (lambda value: value.update({"trust_registry_pin": _digest("0")}), "placeholder"),
        (lambda value: value.update({"dev_gateway_executor_principal_id": "not-a-guid"}), "GUID"),
        (
            lambda value: value.update(
                {
                    "caller_token_jwks": {
                        "keys": [{"kty": "oct", "k": "redacted-symmetric-material"}]
                    }
                }
            ),
            "secret",
        ),
        (lambda value: value.update({"writer_members": ["fdai_core"]}), "writer"),
    ],
)
def test_malformed_inputs_are_rejected(tmp_path: Path, mutate, message: str) -> None:
    value = _input()
    mutate(value)

    with pytest.raises(ValueError, match=message):
        load_operational_evidence_verifier_input(_write(tmp_path / "verifier.json", value))


def test_public_cli_exposes_private_input_path() -> None:
    args = cli._parser().parse_args(
        [
            "provision",
            "azure",
            "--offline-kit",
            "kit.tar.gz",
            "--evidence-verifier-input",
            "verifier.json",
        ]
    )

    assert args.operational_evidence_verifier_input == Path("verifier.json")
