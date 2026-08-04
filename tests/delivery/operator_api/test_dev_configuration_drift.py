from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
)
from fdai.delivery.configuration_baseline_docx import render_configuration_baseline_docx
from fdai.delivery.operator_api.dev.configuration_drift import (
    build_local_configuration_drift_context,
)

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _artifacts(tmp_path: Path) -> dict[str, str]:
    resource = ConfigurationResource(
        local_name="service-a",
        resource_type="example/service",
        region="korea central",
        attributes={"sku_name": "Standard"},
    )
    observation = ConfigurationObservation(
        scope="example-scope",
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=(resource,),
    )
    document = render_configuration_baseline_docx(
        observation=observation,
        version="s13-v1",
        created_at=_NOW,
        source="reviewed inventory snapshot",
    )
    document_path = tmp_path / "baseline.docx"
    document_path.write_bytes(document)
    baseline = FrozenConfigurationBaseline(
        version="s13-v1",
        created_at=_NOW,
        scope=observation.scope,
        source="reviewed inventory snapshot",
        document_sha256=hashlib.sha256(document).hexdigest(),
        resources=observation.resources,
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline.to_dict()), encoding="utf-8")
    observation_path = tmp_path / "observation.json"
    observation_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "scope": observation.scope,
                "observed_at": observation.observed_at.isoformat(),
                "source": observation.source,
                "completeness": observation.completeness.value,
                "resources": [resource.to_dict()],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    return {
        "FDAI_CONFIGURATION_BASELINE_JSON": str(baseline_path),
        "FDAI_CONFIGURATION_BASELINE_DOCX": str(document_path),
        "FDAI_CONFIGURATION_OBSERVATION_JSON": str(observation_path),
    }


def test_builder_is_unbound_when_artifacts_are_not_configured(tmp_path: Path) -> None:
    assert build_local_configuration_drift_context(environ={}, repo_root=tmp_path) is None


def test_builder_rejects_partial_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="incomplete"):
        build_local_configuration_drift_context(
            environ={"FDAI_CONFIGURATION_BASELINE_JSON": "baseline.json"},
            repo_root=tmp_path,
        )


async def test_builder_constructs_exact_cited_resolver(tmp_path: Path) -> None:
    resolver = build_local_configuration_drift_context(
        environ=_artifacts(tmp_path),
        repo_root=tmp_path,
    )

    assert resolver is not None
    result = await resolver.resolve(
        "Use sre-s13-workload-infrastructure-baseline.docx for the baseline.",
        principal_id="reader-1",
    )
    assert result is not None
    assert result["authority"] == "server_knowledge_context"
    assert result["result"]["status"] == "matched"
    assert result["result"]["evidence_refs"]
