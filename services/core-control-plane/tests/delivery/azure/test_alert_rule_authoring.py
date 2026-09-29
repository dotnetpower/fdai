from __future__ import annotations

import json
from pathlib import Path

import pytest
from fdai.delivery.azure.alert_rule_authoring import materialize_metric_alerts
from fdai.delivery.azure.alert_rule_authoring_cli import main
from fdai.delivery.azure.metrics_api import MetricsApiDimensionFilter, MetricsApiTemplate
from fdai.rule_catalog.metric_alerts import (
    MetricAlertCatalogError,
    MetricAlertEntry,
    load_metric_alert_catalog,
)
from pydantic import ValidationError

_PROVENANCE = {
    "source_url": "https://github.com/dotnetpower/fdai",
    "resolved_ref": "metric-alert:example@1.0.0",
    "content_hash": "sha256:" + "a" * 64,
    "license": "MIT",
    "retrieved_at": "2026-09-29T00:00:00Z",
}
_TEMPLATES = {
    "mysql.cpu_percent": MetricsApiTemplate(azure_metric_name="cpu_percent", aggregation="Average"),
    "gateway.backend.unhealthy_host_count": MetricsApiTemplate(
        azure_metric_name="UnhealthyHostCount",
        aggregation="Average",
        resource_type="Microsoft.Network/applicationGateways",
    ),
    "api_gateway.response.429.count": MetricsApiTemplate(
        azure_metric_name="Requests",
        aggregation="Total",
        resource_type="Microsoft.ApiManagement/service",
        dimension_filters=(MetricsApiDimensionFilter("GatewayResponseCode", "429"),),
    ),
    "model.request.count": MetricsApiTemplate(
        azure_metric_name="AzureOpenAIRequests",
        aggregation="Total",
        resource_type="Microsoft.CognitiveServices/accounts",
        deployment_scope=True,
    ),
}


def _entry(**changes: object) -> MetricAlertEntry:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "alert_id": "mysql.cpu-saturation",
        "description": "MySQL CPU sustained above 90 percent.",
        "metric": "mysql.cpu_percent",
        "resource_type": "Microsoft.DBforMySQL/flexibleServers",
        "comparison": "above",
        "threshold": 90,
        "window": "PT5M",
        "frequency": "PT1M",
        "severity": 2,
        "provenance": _PROVENANCE,
    }
    values.update(changes)
    return MetricAlertEntry.model_validate(values)


def test_reviewed_direct_metric_materializes_one_exact_alert() -> None:
    result = materialize_metric_alerts([_entry()], templates=_TEMPLATES)

    assert result.refusals == ()
    [alert] = result.alerts
    assert alert.name == "alert-fdai-mysql-cpu-saturation"
    assert alert.metric_namespace == "Microsoft.DBforMySQL/flexibleServers"
    assert (alert.metric_name, alert.aggregation) == ("cpu_percent", "Average")
    assert (alert.operator, alert.threshold) == ("GreaterThan", 90.0)
    assert (alert.window_size, alert.evaluation_frequency, alert.severity) == ("PT5M", "PT1M", 2)


@pytest.mark.parametrize(
    ("comparison", "operator"),
    [
        ("above", "GreaterThan"),
        ("at_or_above", "GreaterThanOrEqual"),
        ("below", "LessThan"),
        ("at_or_below", "LessThanOrEqual"),
    ],
)
def test_each_static_comparison_maps_to_one_native_operator(comparison: str, operator: str) -> None:
    [alert] = materialize_metric_alerts(
        [_entry(comparison=comparison)], templates=_TEMPLATES
    ).alerts
    assert alert.operator == operator


def test_template_resource_type_supplies_the_namespace() -> None:
    entry = _entry(
        alert_id="gateway.unhealthy-hosts",
        metric="gateway.backend.unhealthy_host_count",
        resource_type=None,
        threshold=0,
    )
    [alert] = materialize_metric_alerts([entry], templates=_TEMPLATES).alerts
    assert alert.metric_namespace == "Microsoft.Network/applicationGateways"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"metric": "unknown.metric"}, "unknown_metric"),
        (
            {"metric": "api_gateway.response.429.count", "resource_type": None},
            "dimension_filtered_metric",
        ),
        ({"metric": "model.request.count", "resource_type": None}, "deployment_scoped_metric"),
        ({"resource_type": None}, "resource_type_missing"),
        (
            {
                "metric": "gateway.backend.unhealthy_host_count",
                "resource_type": "Microsoft.Network/loadBalancers",
            },
            "resource_type_mismatch",
        ),
    ],
)
def test_unsupported_predicates_are_refused_not_approximated(
    changes: dict[str, object], reason: str
) -> None:
    result = materialize_metric_alerts([_entry(**changes)], templates=_TEMPLATES)

    assert result.alerts == ()
    assert [(item.alert_id, item.reason) for item in result.refusals] == [
        ("mysql.cpu-saturation", reason)
    ]


def test_document_digest_is_stable_and_order_independent() -> None:
    first = _entry()
    second = _entry(
        alert_id="gateway.unhealthy-hosts",
        metric="gateway.backend.unhealthy_host_count",
        resource_type=None,
        threshold=0,
    )
    forward = materialize_metric_alerts([first, second], templates=_TEMPLATES).document()
    reverse = materialize_metric_alerts([second, first], templates=_TEMPLATES).document()
    changed = materialize_metric_alerts(
        [
            first,
            _entry(
                alert_id="gateway.unhealthy-hosts",
                metric="gateway.backend.unhealthy_host_count",
                resource_type=None,
                threshold=1,
            ),
        ],
        templates=_TEMPLATES,
    ).document()

    assert forward == reverse
    assert str(forward["digest"]).startswith("sha256:")
    assert changed["digest"] != forward["digest"]
    assert forward["mode"] == "shadow"


@pytest.mark.parametrize(
    "changes",
    [
        {"threshold": float("nan")},
        {"threshold": float("inf")},
        {"window": "PT2M"},
        {"frequency": "PT6H"},
        {"window": "PT1M", "frequency": "PT5M"},
        {"severity": 5},
        {"mode": "enforce"},
        {"comparison": "percent_change_above"},
        {"alert_id": "Bad Id"},
        {"resource_type": "not-an-arm-type"},
        {"unexpected": True},
    ],
)
def test_invalid_entries_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _entry(**changes)


def _write(directory: Path, name: str, **changes: object) -> None:
    payload = _entry(**changes).model_dump(mode="json")
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_catalog_loader_orders_entries_and_rejects_duplicates(tmp_path: Path) -> None:
    _write(tmp_path, "b.yaml", alert_id="zeta.alert")
    _write(tmp_path, "a.yaml", alert_id="alpha.alert")

    assert [item.alert_id for item in load_metric_alert_catalog(tmp_path)] == [
        "alpha.alert",
        "zeta.alert",
    ]
    _write(tmp_path, "c.yaml", alert_id="alpha.alert")
    with pytest.raises(MetricAlertCatalogError, match="duplicate"):
        load_metric_alert_catalog(tmp_path)


def test_catalog_loader_rejects_malformed_entries(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("schema_version: '1.0.0'\n", encoding="utf-8")
    with pytest.raises(MetricAlertCatalogError, match="bad.yaml"):
        load_metric_alert_catalog(tmp_path)


def test_missing_catalog_yields_no_entries(tmp_path: Path) -> None:
    assert load_metric_alert_catalog(tmp_path / "absent") == ()


def test_shipped_catalog_carries_no_active_entries() -> None:
    root = Path(__file__).resolve().parents[5] / "rule-catalog" / "metric-alerts"
    assert load_metric_alert_catalog(root) == ()


def test_cli_is_all_or_nothing_and_checks_staleness(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    _write(catalog, "cpu.yaml", metric="cpu_percent")
    output = tmp_path / "alerts.auto.tfvars.json"

    assert main(["--catalog", str(catalog), "--output", str(output)]) == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert [alert["metric_name"] for alert in document["alerts"]] == ["cpu_percent"]
    assert main(["--catalog", str(catalog), "--output", str(output), "--check"]) == 0

    _write(catalog, "unknown.yaml", alert_id="unknown.alert", metric="unknown.metric")
    before = output.read_text(encoding="utf-8")
    assert main(["--catalog", str(catalog), "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == before
    assert main(["--catalog", str(catalog), "--output", str(output), "--check"]) == 1
