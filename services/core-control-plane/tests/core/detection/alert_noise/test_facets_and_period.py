"""Source-backed facets and exact-period reads, using explicit no-network fixtures."""

from copy import deepcopy
from datetime import timedelta

import pytest
from fdai.core.detection.alert_noise.assessment import assess_alert_noise
from fdai_service_contracts.alert_noise import AlertEvidence, NoiseAssessment, NoisePolicy
from fdai_service_contracts.alert_noise_wire import AlertNoiseCommand, sign_alert_record

from .test_pipeline import _KEY, raw_command, setup


def with_ownership(evidence):
    data = evidence.model_dump(mode="python")
    data["audiences"] = [row.model_dump() for row in evidence.audiences]
    data["audiences"][0]["kind"] = "role"
    data["service_ownership"] = [
        {
            "service_ref": evidence.rules[0].service_ref,
            "team_refs": ["team:example-a", "team:example-b"],
            "stamp": {**evidence.stamp.model_dump(), "source": "test:ownership"},
        }
    ]
    return data


def test_facets_preserve_source_teams_and_audience_kind(evidence, now):
    observed = AlertEvidence.model_validate(with_ownership(evidence))
    report = assess_alert_noise(observed, policy=NoisePolicy(), now=now)
    assert report.findings
    assert all(row.team_refs == ("team:example-a", "team:example-b") for row in report.findings)
    assert all(row.audience_kinds == ("role",) for row in report.findings)
    assert all(observed.rules[0].service_ref not in row.team_refs for row in report.findings)
    assert report.execution_authority is False


def test_one_rule_cannot_project_conflicting_source_facets(evidence, now):
    report = assess_alert_noise(
        AlertEvidence.model_validate(with_ownership(evidence)), policy=NoisePolicy(), now=now
    )
    data = report.model_dump()
    row = report.findings[0].model_dump()
    for changes in ({"team_refs": None}, {"audience_kinds": ("direct",)}):
        with pytest.raises(ValueError, match="facet identity"):
            NoiseAssessment.model_validate({**data, "findings": [row, {**row, **changes}]})


@pytest.mark.parametrize("condition", ["missing", "expired", "partial", "unverified"])
def test_unproven_team_ownership_is_unknown_not_a_service_alias(evidence, now, condition):
    data = with_ownership(evidence)
    if condition == "missing":
        data["service_ownership"] = []
    elif condition == "expired":
        stamp = data["service_ownership"][0]["stamp"]
        stamp.update(
            observed_at=now - timedelta(hours=2),
            recorded_at=now - timedelta(hours=1),
            valid_until=now,
        )
    elif condition == "partial":
        data["service_ownership"][0]["stamp"].update(coverage="partial", reasons=["unresolved"])
    else:
        data["rules"] = [row.model_dump() for row in evidence.rules]
        data["rules"][0]["ownership_verified"] = False
    report = assess_alert_noise(AlertEvidence.model_validate(data), policy=NoisePolicy(), now=now)
    assert report.findings and all(row.team_refs is None for row in report.findings)


@pytest.mark.parametrize(
    "condition", ["scope", "tenant", "future", "synthetic", "service", "duplicate", "order"]
)
def test_facet_source_cannot_escape_scope_or_canonical_identity(evidence, now, condition):
    data = with_ownership(evidence)
    owner = data["service_ownership"][0]
    if condition in {"scope", "tenant"}:
        owner["stamp"][condition + "_ref"] = "other:example"
    elif condition == "future":
        owner["stamp"].update(
            observed_at=now + timedelta(seconds=1), recorded_at=now + timedelta(seconds=1)
        )
    elif condition == "synthetic":
        owner["stamp"]["synthetic"] = False
    elif condition == "service":
        owner["service_ref"] = "service:absent"
    elif condition == "duplicate":
        data["service_ownership"].append(deepcopy(owner))
    else:
        owner["team_refs"].reverse()
    with pytest.raises(ValueError):
        AlertEvidence.model_validate(data)


def test_incomplete_routing_does_not_claim_a_complete_kind_set(evidence, now):
    data = with_ownership(evidence)
    data["groups"] = []
    report = assess_alert_noise(AlertEvidence.model_validate(data), policy=NoisePolicy(), now=now)
    assert report.findings and all(row.audience_kinds is None for row in report.findings)


@pytest.mark.parametrize("period", [3600, 86400, 604800])
@pytest.mark.parametrize("source_mode", ["exact", "wrong", "shifted", "unsupported"])
async def test_period_survives_signed_ingress_or_explicitly_holds(
    evidence, now, period, source_mode
):
    data = evidence.model_dump()
    data["stamp"]["synthetic"] = False
    data["window_start"] = now - timedelta(seconds=period)
    observed = AlertEvidence.model_validate(data)
    huginn, _, handler, source = setup(observed, now)
    raw = raw_command(now)
    value = raw["payload"]["alert_noise"]
    command = AlertNoiseCommand.model_validate({**value["command"], "period_seconds": period})
    value.update(
        command=command.model_dump(mode="json"), signature=sign_alert_record(command, _KEY)
    )
    calls = []
    if source_mode != "unsupported":

        class PeriodSource:
            async def collect(self, *, now):
                raise AssertionError("period selection must not fall back to default collection")

            async def collect_period(self, *, now, period_seconds):
                calls.append(period_seconds)
                if source_mode == "shifted":
                    return observed.model_copy(
                        update={
                            "window_start": observed.window_start - timedelta(hours=1),
                            "window_end": observed.window_end - timedelta(hours=1),
                        }
                    )
                return (
                    observed
                    if source_mode == "exact"
                    else observed.model_copy(
                        update={"window_start": now - timedelta(seconds=period + 3600)}
                    )
                )

        handler.sources["scope:example"] = PeriodSource()
    await huginn.ingest(raw)
    retained = await handler.store.read_state("alert-noise:result:request:example")
    assert retained is not None and source.calls == 0
    result = retained["result"]
    if source_mode == "exact":
        assert calls == [period] and result["status"] == "assessment_ready"
        assert result["command"]["period_seconds"] == period
        assert (
            result["assessment"]["window_start"] == observed.model_dump(mode="json")["window_start"]
        )
    else:
        assert result["status"] == "held" and result["assessment"] is None
        rows, _ = await handler.store.read_state_page("alert-noise:evidence:", limit=10, offset=0)
        assert not rows
