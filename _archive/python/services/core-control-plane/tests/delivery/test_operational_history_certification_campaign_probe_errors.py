"""Focused tests for the bounded probe-error contract of the OI-16 campaign.

Only a concrete transport fault may degrade a scenario to unavailable. A
configuration or programming defect, most often surfacing as ``RuntimeError``,
MUST fail the job so a broken campaign is never published as merely unobserved
evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import psycopg
import pytest
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    OperationalHistoryScenarioStatus,
)
from fdai.core.ontology_platform.operational_history_pressure import StoragePressurePolicy
from fdai.delivery import operational_history_certification_campaign_cli as campaign_cli
from fdai.delivery import operational_history_certification_campaign_runner as campaign_runner
from fdai.delivery.operational_history_certification_campaign import (
    PROBE_TRANSPORT_ERRORS,
    CampaignBinding,
    CampaignPhase,
    OperationalHistoryCertificationCampaign,
    RecoveryBaseline,
    ScenarioObservation,
    SyntheticScope,
)
from fdai.delivery.operational_history_certification_campaign_probes import (
    _PROBE_ERRORS,
    DeployedOperationalHistoryCampaignProbes,
)
from fdai.delivery.operational_history_certification_campaign_release import (
    RELEASE_VERIFIED,
    ReleaseResolution,
)

from tests.delivery.oi16_campaign_deployment_double import FakeDeployment

SCOPE_REF = "synthetic/oi16-certification/campaign-a"
SOURCE = "0123456789abcdef0123456789abcdef01234567"
RELEASE = "sha256:" + "c" * 64
CAMPAIGN_ID = "certify-history-" + "9" * 48
NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)
POLICY = StoragePressurePolicy(
    warning_bytes=10 * 1024**3,
    critical_bytes=20 * 1024**3,
    hard_bytes=30 * 1024**3,
    max_purge_backlog=256,
    max_projection_lag=1000,
)
PROBE_SCENARIO = OperationalHistoryScenario.ARCHIVE_OUTAGE

DEFECTS: tuple[Exception, ...] = (
    RuntimeError("campaign composition is misconfigured"),
    NotImplementedError("probe is not wired"),
    ValueError("campaign binding is malformed"),
    KeyError("missing manifest key"),
    AttributeError("probe defect"),
    TypeError("probe called with the wrong shape"),
    FileNotFoundError("catalog asset is absent"),
    PermissionError("unhandled authorization denial"),
    IsADirectoryError("artifact path is a directory"),
)
TRANSPORT: tuple[Exception, ...] = (
    ConnectionError("archive endpoint refused the connection"),
    ConnectionResetError("archive endpoint reset the connection"),
    TimeoutError("archive endpoint timed out"),
)


def _binding() -> CampaignBinding:
    return CampaignBinding(
        scope=SyntheticScope(environment="dev", scope_ref=SCOPE_REF),
        source_revision=SOURCE,
        ontology_release_digest=RELEASE,
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
        campaign_id_override=CAMPAIGN_ID,
    )


class _RaisingProbes:
    """Raise one prepared error from a single scenario probe."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.observed: list[OperationalHistoryScenario] = []

    async def observe(
        self,
        scenario: OperationalHistoryScenario,
        binding: CampaignBinding,
        *,
        now: datetime,
    ) -> ScenarioObservation | None:
        self.observed.append(scenario)
        if scenario is PROBE_SCENARIO:
            raise self._error
        return None

    async def baseline(self, binding: CampaignBinding, *, now: datetime) -> RecoveryBaseline | None:
        return None


def _deployed(deployment: FakeDeployment) -> DeployedOperationalHistoryCampaignProbes:
    store = cast(Any, deployment)
    return DeployedOperationalHistoryCampaignProbes(
        repository=store,
        history=store,
        archives=store,
        artifacts=store,
        policy=POLICY,
        journal=store,
    )


def _raising_handler(error: Exception) -> Any:
    async def handler(binding: CampaignBinding, now: datetime) -> ScenarioObservation:
        raise error

    return handler


@pytest.mark.parametrize("error", DEFECTS, ids=lambda item: type(item).__name__)
def test_a_configuration_or_programming_defect_is_not_a_transport_fault(
    error: Exception,
) -> None:
    assert not isinstance(error, PROBE_TRANSPORT_ERRORS)
    assert not isinstance(error, _PROBE_ERRORS)


@pytest.mark.parametrize("error", TRANSPORT, ids=lambda item: type(item).__name__)
def test_a_concrete_transport_fault_stays_recoverable(error: Exception) -> None:
    assert isinstance(error, PROBE_TRANSPORT_ERRORS)
    assert isinstance(error, _PROBE_ERRORS)


def test_the_deployed_probe_tuple_keeps_its_provider_transport_types() -> None:
    assert psycopg.Error in _PROBE_ERRORS
    assert httpx.HTTPError in _PROBE_ERRORS
    assert OSError not in _PROBE_ERRORS
    assert RuntimeError not in _PROBE_ERRORS
    assert set(PROBE_TRANSPORT_ERRORS) == {ConnectionError, TimeoutError}
    assert OSError not in PROBE_TRANSPORT_ERRORS
    assert RuntimeError not in PROBE_TRANSPORT_ERRORS


async def test_a_runtime_error_propagates_out_of_the_campaign_core() -> None:
    campaign = OperationalHistoryCertificationCampaign(
        probes=_RaisingProbes(RuntimeError("campaign composition is misconfigured")),
        binding=_binding(),
    )
    with pytest.raises(RuntimeError, match="campaign composition is misconfigured"):
        await campaign.run(now=NOW)


@pytest.mark.parametrize("error", DEFECTS, ids=lambda item: type(item).__name__)
async def test_no_defect_is_downgraded_to_unavailable_evidence(error: Exception) -> None:
    campaign = OperationalHistoryCertificationCampaign(
        probes=_RaisingProbes(error), binding=_binding()
    )
    with pytest.raises(type(error)):
        await campaign.run(now=NOW)


@pytest.mark.parametrize("error", TRANSPORT, ids=lambda item: type(item).__name__)
async def test_a_transport_fault_still_grades_the_scenario_unavailable(error: Exception) -> None:
    campaign = OperationalHistoryCertificationCampaign(
        probes=_RaisingProbes(error), binding=_binding()
    )
    manifest = await campaign.run(now=NOW)
    scenarios = manifest["scenarios"]
    assert isinstance(scenarios, dict)
    entry = scenarios[PROBE_SCENARIO.value]
    assert entry["status"] == OperationalHistoryScenarioStatus.UNAVAILABLE.value
    assert manifest["deterministic_complete"] is False


async def test_a_deployed_probe_runtime_error_is_never_probe_error_unavailable() -> None:
    probes = _deployed(FakeDeployment())
    error = RuntimeError("deployed probe composition is misconfigured")
    setattr(probes, f"_observe_{PROBE_SCENARIO.value}", _raising_handler(error))
    with pytest.raises(RuntimeError, match="deployed probe composition is misconfigured"):
        await probes.observe(PROBE_SCENARIO, _binding(), now=NOW)


@pytest.mark.parametrize("error", DEFECTS, ids=lambda item: type(item).__name__)
async def test_a_deployed_probe_defect_reaches_the_caller(error: Exception) -> None:
    probes = _deployed(FakeDeployment())
    setattr(probes, f"_observe_{PROBE_SCENARIO.value}", _raising_handler(error))
    with pytest.raises(type(error)):
        await probes.observe(PROBE_SCENARIO, _binding(), now=NOW)


@pytest.mark.parametrize(
    "error",
    (
        *TRANSPORT,
        psycopg.OperationalError("database is unreachable"),
        httpx.ConnectError("refused"),
    ),
    ids=lambda item: type(item).__name__,
)
async def test_a_deployed_transport_fault_is_reported_as_unobserved(error: Exception) -> None:
    probes = _deployed(FakeDeployment())
    setattr(probes, f"_observe_{PROBE_SCENARIO.value}", _raising_handler(error))
    observation = await probes.observe(PROBE_SCENARIO, _binding(), now=NOW)
    assert observation is not None
    assert observation.unavailable_reason == "probe_error_unavailable"


def _argv(output: Path) -> list[str]:
    return [
        "--phase",
        "before-restart",
        "--campaign-id",
        CAMPAIGN_ID,
        "--output",
        str(output),
    ]


def _cli_env() -> dict[str, str]:
    return {
        "FDAI_ENV": "dev",
        "FDAI_DATABASE_URL": "postgresql://synthetic",
        "FDAI_OPERATIONAL_HISTORY_CONTAINER_URL": "https://example.invalid/container",
        "FDAI_SOURCE_REVISION": SOURCE,
        "FDAI_ONTOLOGY_RELEASE_DIGEST": RELEASE,
    }


def _prepare_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _cli_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        campaign_cli,
        "resolved_release",
        lambda supplied: ReleaseResolution(
            digest=RELEASE, assertion=RELEASE_VERIFIED, canonical=RELEASE, supplied=RELEASE
        ),
    )


def _failing_run_phase(error: Exception) -> Any:
    async def run_phase(options: object, environ: Mapping[str, str]) -> dict[str, object]:
        raise error

    return run_phase


def test_a_runtime_error_fails_the_job_with_exit_code_two(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_cli(monkeypatch)
    monkeypatch.setattr(
        campaign_runner,
        "run_phase",
        _failing_run_phase(RuntimeError("campaign composition is misconfigured")),
    )
    output = tmp_path / "phase.json"
    assert campaign_cli.main(_argv(output)) == 2
    assert not output.exists()


@pytest.mark.parametrize("error", DEFECTS, ids=lambda item: type(item).__name__)
def test_no_defect_produces_a_manifest_or_a_success_exit_code(
    error: Exception, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_cli(monkeypatch)
    monkeypatch.setattr(campaign_runner, "run_phase", _failing_run_phase(error))
    output = tmp_path / "phase.json"
    assert campaign_cli.main(_argv(output)) == 2
    assert not output.exists()


def test_the_same_harness_reaches_the_runner_and_writes_a_phase_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Prove exit code two above comes from the defect, not from a refused harness."""

    calls: list[str] = []

    async def run_phase(options: Any, environ: Mapping[str, str]) -> dict[str, object]:
        calls.append("run_phase")
        campaign = OperationalHistoryCertificationCampaign(
            probes=_RaisingProbes(ConnectionError("archive endpoint refused the connection")),
            binding=_binding(),
            phase=CampaignPhase.PRE_RESTART,
        )
        return await campaign.run(now=NOW)

    _prepare_cli(monkeypatch)
    monkeypatch.setattr(campaign_runner, "run_phase", run_phase)
    output = tmp_path / "phase.json"
    assert campaign_cli.main(_argv(output)) != 2
    assert calls == ["run_phase"]
    assert json.loads(output.read_text(encoding="utf-8"))["campaign_id"] == CAMPAIGN_ID
