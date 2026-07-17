"""Installable model endpoint discovery CLI tests."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import fdai.delivery.azure.llm.endpoint_discovery_cli as discovery_cli
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelAuthKind,
    ModelCapacityUnit,
    ModelDiscoverySource,
    ModelEndpointBinding,
    ModelEndpointCapacity,
    ModelEndpointDiscovery,
    ModelEndpointFeatures,
    ModelProviderKind,
    ModelRouteKind,
)


def _config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "fdai.model-endpoint-discovery.v1",
                "azure_openai": [
                    {
                        "resource_group": "rg-example",
                        "account_name": "oai-example",
                        "capabilities": [
                            {
                                "capability": "t1.embedding",
                                "deployment": "t1.embedding",
                                "features": {"embeddings": True},
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _resolved(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "region": "koreacentral",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "deployer_object_id": "00000000-0000-0000-0000-000000000001",
                "mixed_model_mode": "hil-only",
                "capabilities": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _binding() -> ModelEndpointBinding:
    return ModelEndpointBinding(
        binding_id="t1-embedding-direct",
        capability="t1.embedding",
        provider_kind=ModelProviderKind.AZURE_OPENAI,
        route_kind=ModelRouteKind.DIRECT,
        api_style=ModelApiStyle.AZURE_OPENAI,
        endpoint_ref="azure-openai:oai-example",
        deployment="t1.embedding",
        api_version="2024-10-21",
        auth_kind=ModelAuthKind.ENTRA,
        auth_audience="https://cognitiveservices.azure.com/.default",
        publisher="OpenAI",
        family="text-embedding-3-small",
        version="1",
        capacity=ModelEndpointCapacity(unit=ModelCapacityUnit.TPM, value=100_000),
        features=ModelEndpointFeatures(embeddings=True),
        discovery=ModelEndpointDiscovery(
            source=ModelDiscoverySource.AZURE_MANAGEMENT,
            resource_ref_digest="a" * 64,
            verified_at=datetime(2026, 7, 17, tzinfo=UTC),
        ),
    )


def test_cli_merges_discovered_bindings_into_private_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def discover(_config):  # noqa: ANN001, ANN202 - focused async seam
        return (_binding(),)

    monkeypatch.setattr(discovery_cli, "_discover", discover)
    output = tmp_path / "protected" / "resolved-models.json"

    exit_code = discovery_cli.main(
        [
            "--config",
            str(_config(tmp_path / "discovery.json")),
            "--resolved-models",
            str(_resolved(tmp_path / "resolved.json")),
            "--out",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["endpoint_bindings"][0]["capability"] == "t1.embedding"
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700


def test_cli_refuses_overwrite_without_force(tmp_path: Path, monkeypatch) -> None:
    async def discover(_config):  # noqa: ANN001, ANN202 - focused async seam
        return (_binding(),)

    monkeypatch.setattr(discovery_cli, "_discover", discover)
    output = tmp_path / "resolved-models.json"
    output.write_text("keep", encoding="utf-8")

    exit_code = discovery_cli.main(
        [
            "--config",
            str(_config(tmp_path / "discovery.json")),
            "--resolved-models",
            str(_resolved(tmp_path / "resolved.json")),
            "--out",
            str(output),
        ]
    )

    assert exit_code == 4
    assert output.read_text(encoding="utf-8") == "keep"


def test_cli_rejects_empty_discovery_config(tmp_path: Path) -> None:
    config = tmp_path / "discovery.json"
    config.write_text(
        json.dumps({"schema_version": "fdai.model-endpoint-discovery.v1"}),
        encoding="utf-8",
    )

    exit_code = discovery_cli.main(
        [
            "--config",
            str(config),
            "--resolved-models",
            str(_resolved(tmp_path / "resolved.json")),
            "--out",
            str(tmp_path / "out.json"),
        ]
    )

    assert exit_code == 4
    assert not (tmp_path / "out.json").exists()
