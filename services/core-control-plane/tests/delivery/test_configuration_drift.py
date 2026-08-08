from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    DriftVerdict,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    KnowledgeGroundingStatus,
)
from fdai.core.detection.configuration_drift_codec import baseline_from_dict
from fdai.core.detection.configuration_drift_service import (
    BaselineIntegrityError,
    ConfigurationDriftService,
)
from fdai.delivery.configuration_drift import (
    ConfigurationDriftToolProvider,
    JsonFileConfigurationBaselineSource,
    JsonFileConfigurationObservationSource,
    build_configuration_drift_bundle,
)
from fdai.shared.providers.knowledge import KnowledgeChunk

_NOW = datetime(2026, 8, 4, tzinfo=UTC)
_DOC_HASH = "a" * 64


def _resource() -> ConfigurationResource:
    return ConfigurationResource(
        local_name="service-a",
        resource_type="example/service",
        region="korea central",
        attributes={"sku": "Standard"},
    )


def _baseline() -> FrozenConfigurationBaseline:
    return FrozenConfigurationBaseline(
        version="s13-v1",
        created_at=_NOW,
        scope="example-scope",
        source="reviewed inventory snapshot",
        document_sha256=_DOC_HASH,
        resources=(_resource(),),
    )


def _observation() -> ConfigurationObservation:
    return ConfigurationObservation(
        scope="example-scope",
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=(_resource(),),
    )


@dataclass
class _BaselineSource:
    baseline: FrozenConfigurationBaseline

    async def load(self) -> FrozenConfigurationBaseline:
        return self.baseline


@dataclass
class _ObservationSource:
    observation: ConfigurationObservation
    requested_scope: str | None = None

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        self.requested_scope = scope
        return self.observation


def _service(
    *,
    baseline: FrozenConfigurationBaseline | None = None,
    observation: ConfigurationObservation | None = None,
    expected_sha256: str | None = None,
) -> ConfigurationDriftService:
    bound_baseline = baseline or _baseline()
    return ConfigurationDriftService(
        baseline_source=_BaselineSource(bound_baseline),
        observation_source=_ObservationSource(observation or _observation()),
        expected_version="s13-v1",
        expected_sha256=expected_sha256 or bound_baseline.sha256,
        expected_scope="example-scope",
    )


@pytest.mark.parametrize(
    ("version", "digest", "scope", "message"),
    [
        ("", "a" * 64, "example-scope", "version and scope"),
        ("s13-v1", "a" * 64, "", "version and scope"),
        ("s13-v1", "not-a-digest", "example-scope", "SHA-256"),
    ],
)
def test_service_rejects_invalid_server_binding(
    version: str,
    digest: str,
    scope: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ConfigurationDriftService(
            baseline_source=_BaselineSource(_baseline()),
            observation_source=_ObservationSource(_observation()),
            expected_version=version,
            expected_sha256=digest,
            expected_scope=scope,
        )


async def test_service_uses_only_server_owned_scope() -> None:
    observation_source = _ObservationSource(_observation())
    baseline = _baseline()
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=observation_source,
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
    )

    report = await service.run()

    assert report.verdict is DriftVerdict.PASSED
    assert observation_source.requested_scope == "example-scope"


async def test_service_records_fresh_stage_performance_receipt() -> None:
    ticks = iter((0.0, 0.01, 0.04, 0.05, 0.07))
    baseline = _baseline()
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(_observation()),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        monotonic=lambda: next(ticks),
    )

    report = await service.run()

    assert report.performance is not None
    assert report.performance.baseline_load_ms == pytest.approx(10.0)
    assert report.performance.observation_ms == pytest.approx(30.0)
    assert report.performance.comparison_ms == pytest.approx(10.0)
    assert report.performance.knowledge_ms == pytest.approx(20.0)
    assert report.performance.total_ms == pytest.approx(70.0)
    assert report.performance.resource_count == 1
    assert report.performance.finding_count == len(report.findings)


async def test_service_rejects_changed_baseline_before_observation() -> None:
    observation_source = _ObservationSource(_observation())
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(_baseline()),
        observation_source=observation_source,
        expected_version="s13-v1",
        expected_sha256="0" * 64,
        expected_scope="example-scope",
    )

    with pytest.raises(BaselineIntegrityError, match="digest"):
        await service.run()

    assert observation_source.requested_scope is None


async def test_service_rejects_changed_version_before_observation() -> None:
    observation_source = _ObservationSource(_observation())
    baseline = replace(_baseline(), version="s13-v2")
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=observation_source,
        expected_version="s13-v1",
        expected_sha256=baseline.sha256,
        expected_scope="example-scope",
    )

    with pytest.raises(BaselineIntegrityError, match="version"):
        await service.run()

    assert observation_source.requested_scope is None


async def test_service_rejects_observation_scope_escape() -> None:
    baseline = _baseline()
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(
            replace(_observation(), scope="another-scope"),
        ),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
    )

    with pytest.raises(BaselineIntegrityError, match="escaped"):
        await service.run()


async def test_tool_provider_returns_blocked_without_exception_details() -> None:
    bundle = build_configuration_drift_bundle(_service(expected_sha256="0" * 64))
    artifact = bundle.reasoning_tools[0]
    provider = bundle.tool_providers[artifact.provider or ""]

    result = await provider.call(artifact=artifact, arguments={})

    assert isinstance(result, dict)
    assert result["verdict"] == "blocked"
    assert result["error_code"] == "configuration_evidence_unavailable:BaselineIntegrityError"
    assert result["mutation_count"] == 0
    assert "digest" not in json.dumps(result)


async def test_tool_provider_returns_deterministic_report() -> None:
    bundle = build_configuration_drift_bundle(_service())
    artifact = bundle.reasoning_tools[0]
    provider = bundle.tool_providers[artifact.provider or ""]

    result = await provider.call(artifact=artifact, arguments={})

    assert isinstance(result, dict)
    assert result["verdict"] == "passed"
    assert result["baseline_version"] == "s13-v1"
    assert result["mutation_count"] == 0
    assert bundle.capabilities[0].side_effect_class.value == "read"


def test_json_sources_round_trip_and_enforce_scope(tmp_path: Path) -> None:
    baseline = _baseline()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline.to_dict()), encoding="utf-8")
    observation_path = tmp_path / "observation.json"
    observation_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "scope": "example-scope",
                "observed_at": _NOW.isoformat(),
                "source": "authoritative inventory",
                "completeness": "complete",
                "resources": [_resource().to_dict()],
                "links": [],
            }
        ),
        encoding="utf-8",
    )

    assert isinstance(JsonFileConfigurationBaselineSource(baseline_path), object)
    assert isinstance(
        JsonFileConfigurationObservationSource(observation_path, "example-scope"), object
    )
    assert baseline_from_dict(json.loads(baseline_path.read_text())).sha256 == baseline.sha256


def test_codec_rejects_unknown_fields() -> None:
    raw = _baseline().to_dict()
    raw["unexpected"] = True

    with pytest.raises(ValueError, match="unknown fields"):
        baseline_from_dict(raw)


async def test_file_observation_source_rejects_content_outside_scope(tmp_path: Path) -> None:
    path = tmp_path / "observation.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "scope": "other-scope",
                "observed_at": _NOW.isoformat(),
                "source": "authoritative inventory",
                "completeness": "complete",
                "resources": [],
                "links": [],
            }
        ),
        encoding="utf-8",
    )
    source = JsonFileConfigurationObservationSource(path, "example-scope")

    with pytest.raises(PermissionError, match="outside"):
        await source.observe(scope="example-scope")


async def test_tool_rejects_caller_arguments() -> None:
    provider = ConfigurationDriftToolProvider(_service())
    artifact = build_configuration_drift_bundle(_service()).reasoning_tools[0]

    with pytest.raises(ValueError, match="no caller arguments"):
        await provider.call(artifact=artifact, arguments={"scope": "other"})


@dataclass
class _KnowledgeSource:
    chunks: tuple[KnowledgeChunk, ...] = ()
    error: Exception | None = None

    async def ingest(self, documents: object) -> int:
        del documents
        return 0

    async def search(self, query: str, *, k: int = 5) -> tuple[KnowledgeChunk, ...]:
        del query, k
        if self.error is not None:
            raise self.error
        return self.chunks


async def test_service_cites_only_exact_baseline_knowledge() -> None:
    baseline = _baseline()
    source = _KnowledgeSource(
        chunks=(
            KnowledgeChunk(
                doc_id="baseline",
                chunk_id="baseline#0",
                text="reviewed baseline",
                source_ref="baseline.docx",
                score=1.0,
                metadata={
                    "baseline_version": baseline.version,
                    "document_sha256": baseline.document_sha256,
                },
            ),
        )
    )
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(_observation()),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        knowledge_source=source,
    )

    report = await service.run()

    assert report.verdict is DriftVerdict.PASSED
    assert report.knowledge_status is KnowledgeGroundingStatus.CITED
    assert report.knowledge_citations == ("knowledge:baseline.docx#baseline#0",)


async def test_service_blocks_mismatched_knowledge_metadata() -> None:
    baseline = _baseline()
    source = _KnowledgeSource(
        chunks=(
            KnowledgeChunk(
                doc_id="baseline",
                chunk_id="baseline#0",
                text="wrong baseline",
                source_ref="baseline.docx",
                score=1.0,
                metadata={
                    "baseline_version": "another-version",
                    "document_sha256": baseline.document_sha256,
                },
            ),
        )
    )
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(_observation()),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        knowledge_source=source,
    )

    report = await service.run()

    assert report.verdict is DriftVerdict.PASSED
    assert report.knowledge_status is KnowledgeGroundingStatus.BLOCKED
    assert report.knowledge_citations == ()


@pytest.mark.parametrize("source", [_KnowledgeSource(), _KnowledgeSource(error=TimeoutError())])
async def test_knowledge_failure_is_blocked_without_changing_drift_verdict(
    source: _KnowledgeSource,
) -> None:
    baseline = _baseline()
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(_observation()),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        knowledge_source=source,
    )

    report = await service.run()

    assert report.verdict is DriftVerdict.PASSED
    assert report.knowledge_status is KnowledgeGroundingStatus.BLOCKED
    assert report.knowledge_citations == ()


async def test_knowledge_exception_emits_secret_safe_structured_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    baseline = _baseline()
    service = ConfigurationDriftService(
        baseline_source=_BaselineSource(baseline),
        observation_source=_ObservationSource(_observation()),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        knowledge_source=_KnowledgeSource(error=RuntimeError("secret-bearing provider detail")),
    )

    with caplog.at_level(logging.WARNING):
        report = await service.run()

    assert report.knowledge_status is KnowledgeGroundingStatus.BLOCKED
    record = next(
        item for item in caplog.records if item.message == "configuration_drift_knowledge_failed"
    )
    assert record.error_type == "RuntimeError"
    assert record.baseline_version == baseline.version
    assert "secret-bearing" not in caplog.text
