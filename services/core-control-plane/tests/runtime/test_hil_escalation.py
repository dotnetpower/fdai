"""Runtime assembly loads real catalogs without provider reads or mode promotion."""

from __future__ import annotations

from pathlib import Path

import pytest
from fdai.runtime.hil_escalation import (
    build_escalation_timing,
    build_forecast_urgency_reader,
    build_rung_eligibility,
)

ROOT = Path(__file__).resolve().parents[4]


def test_runtime_binds_existing_core_forecast_source_without_connecting(monkeypatch):
    import psycopg
    from fdai.delivery.persistence.postgres_forecast_urgency import PostgresForecastUrgencyReader

    def unexpected(*args, **kwargs):
        raise AssertionError("composition must not query a provider")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", unexpected)
    assert build_forecast_urgency_reader({}) is None
    reader = build_forecast_urgency_reader(
        {"FDAI_STATE_STORE_DSN": "host=localhost dbname=example"}
    )
    assert isinstance(reader, PostgresForecastUrgencyReader)


def test_runtime_loads_shipped_catalog_with_explicit_unavailable_audience():
    timing = build_escalation_timing(
        ROOT / "rule-catalog", {"FDAI_HIL_ESCALATION_ENVIRONMENT": "prod"}
    )
    assert len(timing.catalog.ladders) == 2
    result = timing.resolve(
        {"finding_class": "forecast.breach", "impact": "resource_group"}, ("human:primary",)
    )
    assert result["catalog_status"] == "audience_unavailable"
    assert (
        build_rung_eligibility(
            ROOT / "rule-catalog", http_client=None, identity=None, environment={}
        )
        is None
    )


@pytest.mark.parametrize(
    "raw",
    ["[]", "null", '{"example":[]}', '{"example":[true]}', '{"example":["a","b"]}', "invalid"],
)
def test_runtime_rejects_ambiguous_audience_binding(raw):
    with pytest.raises(ValueError):
        build_escalation_timing(ROOT / "rule-catalog", {"FDAI_HIL_ESCALATION_AUDIENCES_JSON": raw})


def test_runtime_uses_exact_audience_bindings_and_never_positional_substitution():
    timing = build_escalation_timing(
        ROOT / "rule-catalog",
        {
            "FDAI_HIL_ESCALATION_ENVIRONMENT": "nonprod",
            "FDAI_HIL_ESCALATION_AUDIENCES_JSON": '{"aw-service-owner":["human:owner"]}',
        },
    )
    context = {"finding_class": "forecast.breach", "impact": "resource"}
    assert timing.resolve(context, ("human:owner",))["catalog_status"] == "resolved"
    assert timing.resolve(context, ("different-human",))["catalog_status"] == "audience_mismatch"


def test_missing_environment_does_not_assume_nonproduction():
    timing = build_escalation_timing(ROOT / "rule-catalog", {})
    result = timing.resolve({"finding_class": "forecast.breach", "impact": "resource"}, ())
    assert result["catalog_status"] == "no_matching_ladder"
