from __future__ import annotations

import base64
import gzip
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
)
from fdai.core.detection.configuration_drift_codec import baseline_from_dict

_ROOT = Path(__file__).resolve().parents[3]
_PATH = _ROOT / "scripts/deployment/azure/configuration_baseline_evidence.py"
_SPEC = importlib.util.spec_from_file_location("configuration_baseline_evidence", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def _binding(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "fdai.configuration-baseline-binding.v1",
        "baseline_version": "example-v1",
        "baseline_sha256": "a" * 64,
        "created_at": "2026-09-10T00:00:00+00:00",
        "document_sha256": "b" * 64,
        "source": "reviewed snapshot",
        "scope": "scope:example",
        "subscription_scopes": ["00000000-0000-0000-0000-000000000001"],
        "attribute_paths": ["properties.publicNetworkAccess", "sku.name"],
        "resource_count": 1,
        "finding_count": 5,
        "comparison_verdict": "passed",
        "arg_endpoint": "https://management.azure.com",
    }
    value.update(overrides)
    return value


def _approved_envelope() -> tuple[dict[str, object], str]:
    baseline = {
        "schema_version": "1.0.0",
        "version": "example-v1",
        "created_at": "2026-09-10T00:00:00+00:00",
        "document_sha256": "b" * 64,
        "source": "reviewed snapshot",
        "scope": "scope:example",
        "resources": [
            {
                "local_name": "widget#0000000000000000",
                "resource_type": "example/widgets",
                "region": "example-region",
                "attributes": {"sku.name": "Standard"},
                "unknown_attributes": [],
                "unauthorized_attributes": [],
            }
        ],
        "links": [],
        "allowed_exceptions": [],
        "unknown_items": [],
    }
    encoded = base64.b64encode(
        gzip.compress(json.dumps(baseline).encode(), compresslevel=9, mtime=0)
    ).decode()
    return baseline, encoded


def test_binding_is_strict_and_builds_content_addressed_blob_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CONFIGURATION_BASELINE_BINDING_JSON",
        json.dumps(_binding()),
    )
    monkeypatch.setenv(
        "CONFIGURATION_BASELINE_CONTAINER_URL",
        "https://example.blob.core.windows.net/decision-evidence",
    )

    binding = _MODULE.BaselineBinding.from_environment()

    assert binding.resource_count == 1
    assert binding.blob_url.endswith(f"/configuration-baselines/{'a' * 64}.json")


def test_prepare_decodes_exact_reviewed_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    baseline, encoded = _approved_envelope()
    binding = _binding(baseline_sha256=baseline_from_dict(baseline).sha256)
    monkeypatch.setenv("CONFIGURATION_BASELINE_BINDING_JSON", json.dumps(binding))
    monkeypatch.setenv("CONFIGURATION_BASELINE_GZIP_BASE64", encoded)
    monkeypatch.setenv(
        "CONFIGURATION_BASELINE_CONTAINER_URL",
        "https://example.blob.core.windows.net/decision-evidence",
    )
    tfvars = tmp_path / "service.tfvars.json"
    tfvars.write_text('{"name":"example"}', encoding="utf-8")

    _MODULE.prepare(baseline_path=tmp_path / "baseline.json", tfvars_path=tfvars)

    materialized = json.loads(tfvars.read_text(encoding="utf-8"))
    assert materialized["name"] == "example"
    assert materialized["configuration_drift"]["baseline_sha256"] == binding["baseline_sha256"]
    assert (tmp_path / "baseline.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("encoded", ("not-base64", base64.b64encode(b"not-gzip").decode()))
def test_prepare_rejects_invalid_envelopes(
    monkeypatch: pytest.MonkeyPatch,
    encoded: str,
) -> None:
    monkeypatch.setenv("CONFIGURATION_BASELINE_BINDING_JSON", json.dumps(_binding()))
    monkeypatch.setenv("CONFIGURATION_BASELINE_GZIP_BASE64", encoded)

    with pytest.raises(ValueError, match="envelope"):
        _MODULE._approved_baseline(_MODULE.BaselineBinding.from_environment())


@pytest.mark.parametrize(
    "overrides",
    (
        {"scope": ""},
        {"baseline_sha256": "not-a-digest"},
        {"resource_count": 0},
        {"finding_count": 0},
        {"comparison_verdict": "failed"},
        {"attribute_paths": ["sku.name", "properties.value"]},
    ),
)
def test_binding_rejects_incomplete_or_unreviewed_values(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    monkeypatch.setenv(
        "CONFIGURATION_BASELINE_BINDING_JSON",
        json.dumps(_binding(**overrides)),
    )

    with pytest.raises(ValueError):
        _MODULE.BaselineBinding.from_environment()


def test_runtime_readback_requires_every_exact_binding_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binding = _binding()
    monkeypatch.setenv("CONFIGURATION_BASELINE_BINDING_JSON", json.dumps(binding))
    monkeypatch.setenv(
        "CONFIGURATION_BASELINE_CONTAINER_URL",
        "https://example.blob.core.windows.net/decision-evidence",
    )
    expected = _MODULE.BaselineBinding.from_environment()
    app = {
        "properties": {
            "template": {
                "containers": [
                    {
                        "name": "core-control-plane",
                        "env": [
                            {"name": "FDAI_CONFIGURATION_DRIFT_ENABLED", "value": "1"},
                            {
                                "name": "FDAI_CONFIGURATION_BASELINE_URL",
                                "value": expected.blob_url,
                            },
                            {
                                "name": "FDAI_CONFIGURATION_BASELINE_VERSION",
                                "value": binding["baseline_version"],
                            },
                            {
                                "name": "FDAI_CONFIGURATION_BASELINE_SHA256",
                                "value": binding["baseline_sha256"],
                            },
                            {
                                "name": "FDAI_CONFIGURATION_SCOPE",
                                "value": binding["scope"],
                            },
                            {
                                "name": "FDAI_CONFIGURATION_SUBSCRIPTIONS_JSON",
                                "value": json.dumps(
                                    binding["subscription_scopes"],
                                    separators=(",", ":"),
                                ),
                            },
                            {
                                "name": "FDAI_CONFIGURATION_ATTRIBUTE_PATHS_JSON",
                                "value": json.dumps(
                                    binding["attribute_paths"],
                                    separators=(",", ":"),
                                ),
                            },
                            {
                                "name": "FDAI_CONFIGURATION_ARG_ENDPOINT",
                                "value": binding["arg_endpoint"],
                            },
                        ],
                    }
                ]
            }
        }
    }
    path = tmp_path / "app.json"
    path.write_text(json.dumps(app), encoding="utf-8")

    _MODULE.verify_runtime(app_path=path)
    app["properties"]["template"]["containers"][0]["env"][0]["value"] = "0"
    path.write_text(json.dumps(app), encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match"):
        _MODULE.verify_runtime(app_path=path)


def test_sanitized_receipt_shape_contains_no_resource_identity() -> None:
    observation = ConfigurationObservation(
        scope="scope:example",
        observed_at=datetime(2026, 9, 10, tzinfo=UTC),
        source="azure_resource_graph",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=(
            ConfigurationResource(
                local_name="private-resource#0000000000000000",
                resource_type="example/widgets",
                region="example-region",
                attributes={"sku.name": "Standard"},
            ),
        ),
    )

    assert observation.completeness is EvidenceCompleteness.COMPLETE
    source = _PATH.read_text(encoding="utf-8")
    assert '"scope_sha256"' in source
    assert '"failed_finding_count"' in source
    assert '"mutation_count"' in source
    assert '"approval_request_count"' in source
    assert '"mitigation_execution_count"' in source
    assert (
        '"resources"'
        not in source[source.index("sanitized = {") : source.index("output_path.write_text")]
    )
