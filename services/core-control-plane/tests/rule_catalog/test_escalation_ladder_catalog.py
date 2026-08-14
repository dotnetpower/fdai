"""Focused evidence for the approval-escalation ladder and urgency catalog.

Covers what the escalation design promises and what a reviewer of a shipped
ladder needs proven: expiry, fallback delivery, starvation prevention, and
deterministic replay.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.schema.escalation_ladder import (
    EscalationCatalog,
    EscalationCatalogError,
    EscalationLadder,
    EscalationRung,
    LadderSelector,
    UrgencyPolicy,
    fallback_channels,
    load_escalation_catalog,
    resolve_schedule,
    rung_at_elapsed,
    select_ladder,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_ROOT = REPO_ROOT / "rule-catalog/escalation-ladders"


def _write(root: Path, name: str, payload: dict[str, object]) -> None:
    (root / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _copy_schemas(root: Path) -> None:
    for schema in ("escalation-ladder.schema.json", "urgency-policy.schema.json"):
        (root / schema).write_text(
            (CATALOG_ROOT / schema).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _ladder_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "kind": "escalation_ladder",
        "id": "sample-ladder",
        "priority": 10,
        "select_when": {
            "environment": "prod",
            "finding_class": "forecast.breach",
            "impact_at_least": "resource_group",
        },
        "rungs": [
            {
                "rung": "on_call_primary",
                "audience_group": "aw-oncall-primary",
                "ttl_seconds": 300,
                "category": "hil_approval",
            },
            {
                "rung": "incident_commander",
                "audience_group": "aw-incident-commander",
                "ttl_seconds": 600,
                "category": "hil_approval",
                "also_page": ["pagerduty-primary"],
            },
        ],
        "overall_deadline_seconds": 1200,
    }
    payload.update(overrides)
    return payload


def _ladder(**overrides: object) -> EscalationLadder:
    rungs = overrides.pop("rungs", None) or (
        EscalationRung("on_call_primary", "aw-oncall-primary", 300, "hil_approval"),
        EscalationRung(
            "incident_commander",
            "aw-incident-commander",
            600,
            "hil_approval",
            also_page=("pagerduty-primary",),
        ),
    )
    defaults: dict[str, object] = {
        "id": "sample-ladder",
        "priority": 10,
        "select_when": LadderSelector("prod", "forecast.breach", "resource_group"),
        "rungs": tuple(rungs),
        "overall_deadline_seconds": 1200,
    }
    defaults.update(overrides)
    return EscalationLadder(**defaults)  # type: ignore[arg-type]


def _policy(**overrides: object) -> UrgencyPolicy:
    defaults: dict[str, object] = {
        "id": "default-forecast-urgency",
        "lead_time_factor": 0.5,
        "min_forecast_confidence": 0.9,
        "min_effective_ttl_seconds": 60,
    }
    defaults.update(overrides)
    return UrgencyPolicy(**defaults)  # type: ignore[arg-type]


class TestShippedCatalog:
    def test_the_shipped_catalog_loads(self) -> None:
        catalog = load_escalation_catalog(CATALOG_ROOT)

        assert {ladder.id for ladder in catalog.ladders} == {
            "prod-forecast-breach",
            "nonprod-standard",
        }
        assert {policy.id for policy in catalog.urgency_policies} == {"default-forecast-urgency"}

    def test_every_shipped_rung_fits_inside_its_deadline(self) -> None:
        catalog = load_escalation_catalog(CATALOG_ROOT)

        for ladder in catalog.ladders:
            assert ladder.declared_walk_seconds <= ladder.overall_deadline_seconds

    def test_ladders_are_returned_in_priority_order(self) -> None:
        catalog = load_escalation_catalog(CATALOG_ROOT)

        priorities = [ladder.priority for ladder in catalog.ladders]
        assert priorities == sorted(priorities)

    def test_a_named_urgency_policy_resolves(self) -> None:
        catalog = load_escalation_catalog(CATALOG_ROOT)

        assert catalog.urgency_policy("default-forecast-urgency") is not None
        assert catalog.urgency_policy("no-such-policy") is None


class TestCatalogLoadFailsClosed:
    def test_an_empty_directory_loads_an_empty_catalog(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)

        assert load_escalation_catalog(tmp_path) == EscalationCatalog()

    def test_a_missing_root_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_escalation_catalog(tmp_path / "absent")

    def test_an_unknown_kind_is_rejected(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)
        _write(tmp_path, "a.yaml", _ladder_payload(kind="standing_authority"))

        with pytest.raises(EscalationCatalogError) as excinfo:
            load_escalation_catalog(tmp_path)

        assert any("kind must be" in issue.message for issue in excinfo.value.issues)

    def test_a_schema_violation_is_rejected(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)
        payload = _ladder_payload()
        payload["rungs"] = []
        _write(tmp_path, "a.yaml", payload)

        with pytest.raises(EscalationCatalogError):
            load_escalation_catalog(tmp_path)

    def test_a_duplicate_ladder_id_is_rejected(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)
        _write(tmp_path, "a.yaml", _ladder_payload())
        _write(tmp_path, "b.yaml", _ladder_payload(priority=20))

        with pytest.raises(EscalationCatalogError) as excinfo:
            load_escalation_catalog(tmp_path)

        assert any("duplicate ladder id" in issue.message for issue in excinfo.value.issues)

    def test_a_duplicate_priority_is_rejected_so_selection_stays_deterministic(
        self, tmp_path: Path
    ) -> None:
        _copy_schemas(tmp_path)
        _write(tmp_path, "a.yaml", _ladder_payload())
        _write(tmp_path, "b.yaml", _ladder_payload(id="other-ladder"))

        with pytest.raises(EscalationCatalogError) as excinfo:
            load_escalation_catalog(tmp_path)

        assert any("duplicate priority" in issue.message for issue in excinfo.value.issues)

    def test_an_unreachable_rung_is_rejected(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)
        _write(tmp_path, "a.yaml", _ladder_payload(overall_deadline_seconds=400))

        with pytest.raises(EscalationCatalogError) as excinfo:
            load_escalation_catalog(tmp_path)

        assert any("unreachable" in issue.message for issue in excinfo.value.issues)

    def test_a_rung_that_pages_its_own_deciding_audience_is_rejected(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)
        payload = _ladder_payload()
        rungs = list(payload["rungs"])  # type: ignore[arg-type]
        rungs[0] = {**rungs[0], "also_page": ["aw-oncall-primary"]}  # type: ignore[dict-item]
        payload["rungs"] = rungs
        _write(tmp_path, "a.yaml", payload)

        with pytest.raises(EscalationCatalogError) as excinfo:
            load_escalation_catalog(tmp_path)

        assert any("never approval authority" in issue.message for issue in excinfo.value.issues)

    def test_a_duplicate_rung_name_is_rejected(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)
        payload = _ladder_payload()
        rungs = list(payload["rungs"])  # type: ignore[arg-type]
        rungs[1] = {**rungs[1], "rung": "on_call_primary"}  # type: ignore[dict-item]
        payload["rungs"] = rungs
        _write(tmp_path, "a.yaml", payload)

        with pytest.raises(EscalationCatalogError) as excinfo:
            load_escalation_catalog(tmp_path)

        assert any("duplicate rung" in issue.message for issue in excinfo.value.issues)

    def test_invalid_yaml_is_rejected(self, tmp_path: Path) -> None:
        _copy_schemas(tmp_path)
        (tmp_path / "a.yaml").write_text("kind: [unclosed\n", encoding="utf-8")

        with pytest.raises(EscalationCatalogError) as excinfo:
            load_escalation_catalog(tmp_path)

        assert any("invalid YAML" in issue.message for issue in excinfo.value.issues)


class TestLadderSelection:
    def test_the_first_matching_ladder_by_priority_wins(self) -> None:
        catalog = EscalationCatalog(
            ladders=(_ladder(id="specific", priority=5), _ladder(id="broad", priority=50))
        )

        selected = select_ladder(
            catalog, environment="prod", finding_class="forecast.breach", impact="resource_group"
        )

        assert selected is not None and selected.id == "specific"

    def test_a_wider_impact_still_matches_the_declared_minimum(self) -> None:
        catalog = EscalationCatalog(ladders=(_ladder(),))

        selected = select_ladder(
            catalog, environment="prod", finding_class="forecast.breach", impact="subscription"
        )

        assert selected is not None

    def test_a_narrower_impact_does_not_match(self) -> None:
        catalog = EscalationCatalog(ladders=(_ladder(),))

        selected = select_ladder(
            catalog, environment="prod", finding_class="forecast.breach", impact="resource"
        )

        assert selected is None

    def test_a_different_environment_does_not_match(self) -> None:
        catalog = EscalationCatalog(ladders=(_ladder(),))

        assert (
            select_ladder(
                catalog,
                environment="nonprod",
                finding_class="forecast.breach",
                impact="subscription",
            )
            is None
        )

    def test_an_unknown_impact_is_an_error_rather_than_a_silent_miss(self) -> None:
        catalog = EscalationCatalog(ladders=(_ladder(),))

        with pytest.raises(ValueError, match="unknown impact"):
            select_ladder(
                catalog, environment="prod", finding_class="forecast.breach", impact="tenant"
            )


class TestScheduleAndExpiry:
    def test_without_a_forecast_every_rung_runs_its_declared_ttl(self) -> None:
        schedule = resolve_schedule(_ladder())

        assert [window.effective_ttl_seconds for window in schedule] == [300, 600]
        assert [window.expires_at_seconds for window in schedule] == [300, 900]
        assert not any(window.compressed for window in schedule)

    def test_the_rung_owning_an_instant_is_returned(self) -> None:
        schedule = resolve_schedule(_ladder())

        assert rung_at_elapsed(schedule, 0).rung.rung == "on_call_primary"  # type: ignore[union-attr]
        assert rung_at_elapsed(schedule, 299).rung.rung == "on_call_primary"  # type: ignore[union-attr]
        assert rung_at_elapsed(schedule, 300).rung.rung == "incident_commander"  # type: ignore[union-attr]

    def test_past_the_last_rung_the_ladder_is_a_terminal_no_op(self) -> None:
        schedule = resolve_schedule(_ladder())

        assert rung_at_elapsed(schedule, 900) is None
        assert rung_at_elapsed(schedule, 100_000) is None

    def test_a_negative_elapsed_time_is_an_error(self) -> None:
        schedule = resolve_schedule(_ladder())

        with pytest.raises(ValueError, match="elapsed_seconds"):
            rung_at_elapsed(schedule, -1)


class TestUrgencyCompression:
    def test_a_closing_forecast_compresses_every_rung(self) -> None:
        schedule = resolve_schedule(
            _ladder(),
            policy=_policy(),
            remaining_lead_time_seconds=400,
            forecast_confidence=0.95,
        )

        assert [window.effective_ttl_seconds for window in schedule] == [200, 200]
        assert all(window.compressed for window in schedule)

    def test_compression_never_lengthens_a_declared_ttl(self) -> None:
        schedule = resolve_schedule(
            _ladder(),
            policy=_policy(),
            remaining_lead_time_seconds=100_000,
            forecast_confidence=1.0,
        )

        assert [window.effective_ttl_seconds for window in schedule] == [300, 600]

    def test_a_low_confidence_forecast_does_not_compress(self) -> None:
        schedule = resolve_schedule(
            _ladder(),
            policy=_policy(),
            remaining_lead_time_seconds=10,
            forecast_confidence=0.5,
        )

        assert [window.effective_ttl_seconds for window in schedule] == [300, 600]

    def test_a_missing_forecast_does_not_compress(self) -> None:
        schedule = resolve_schedule(_ladder(), policy=_policy())

        assert [window.effective_ttl_seconds for window in schedule] == [300, 600]

    def test_the_starvation_floor_keeps_a_usable_window(self) -> None:
        schedule = resolve_schedule(
            _ladder(),
            policy=_policy(),
            remaining_lead_time_seconds=0,
            forecast_confidence=1.0,
        )

        assert [window.effective_ttl_seconds for window in schedule] == [60, 60]

    def test_a_declared_ttl_below_the_floor_is_still_never_lengthened(self) -> None:
        ladder = _ladder(
            rungs=(EscalationRung("fast", "aw-oncall-primary", 30, "hil_approval"),),
            overall_deadline_seconds=60,
        )

        schedule = resolve_schedule(
            ladder, policy=_policy(), remaining_lead_time_seconds=0, forecast_confidence=1.0
        )

        assert schedule[0].effective_ttl_seconds == 30

    def test_a_negative_lead_time_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="remaining_lead_time_seconds"):
            resolve_schedule(_ladder(), policy=_policy(), remaining_lead_time_seconds=-1)

    def test_an_out_of_range_confidence_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="forecast_confidence"):
            resolve_schedule(_ladder(), policy=_policy(), forecast_confidence=1.5)


class TestDeterministicReplay:
    def test_the_same_inputs_produce_the_same_schedule(self) -> None:
        kwargs = {
            "policy": _policy(),
            "remaining_lead_time_seconds": 480,
            "forecast_confidence": 0.93,
        }

        first = resolve_schedule(_ladder(), **kwargs)  # type: ignore[arg-type]
        second = resolve_schedule(_ladder(), **kwargs)  # type: ignore[arg-type]

        assert first == second

    def test_the_schedule_records_the_inputs_needed_to_replay_it(self) -> None:
        schedule = resolve_schedule(
            _ladder(),
            policy=_policy(),
            remaining_lead_time_seconds=480,
            forecast_confidence=0.93,
        )

        assert schedule[0].metadata == {
            "ladder_id": "sample-ladder",
            "urgency_policy_id": "default-forecast-urgency",
        }

    def test_an_uncompressed_schedule_records_no_policy(self) -> None:
        schedule = resolve_schedule(_ladder())

        assert schedule[0].metadata["urgency_policy_id"] == ""


class TestFallbackDelivery:
    def test_paging_channels_are_collected_in_ladder_order(self) -> None:
        ladder = _ladder(
            rungs=(
                EscalationRung(
                    "on_call_primary",
                    "aw-oncall-primary",
                    300,
                    "hil_approval",
                    also_page=("pagerduty-primary",),
                ),
                EscalationRung(
                    "incident_commander",
                    "aw-incident-commander",
                    600,
                    "hil_approval",
                    also_page=("pagerduty-primary", "sms-oncall"),
                ),
            )
        )

        assert fallback_channels(resolve_schedule(ladder)) == ("pagerduty-primary", "sms-oncall")

    def test_a_ladder_without_paging_has_no_fallback_channels(self) -> None:
        ladder = _ladder(
            rungs=(EscalationRung("service_owner", "aw-service-owner", 300, "hil_approval"),),
            overall_deadline_seconds=600,
        )

        assert fallback_channels(resolve_schedule(ladder)) == ()

    def test_the_shipped_production_ladder_pages_as_it_climbs(self) -> None:
        catalog = load_escalation_catalog(CATALOG_ROOT)
        ladder = select_ladder(
            catalog, environment="prod", finding_class="forecast.breach", impact="resource_group"
        )
        assert ladder is not None

        schedule = resolve_schedule(ladder)

        assert schedule[0].rung.also_page == ()
        assert fallback_channels(schedule) == ("pagerduty-primary", "sms-oncall")
