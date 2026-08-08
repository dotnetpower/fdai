"""Wave M1.5c - coordinator verb + arg wiring for read-tool verbs.

Covers the 5 read verbs landed since Day-1's baseline:

- ``query_operator_memory`` (W1.6)
- ``query_log`` (M1.5b)
- ``query_metric`` (M1.5b)
- ``query_deployments`` (M1.5b)
- ``correlate_incident`` (M1.5b)

Matches the shape of ``test_write_verbs_wiring.py``: pattern-matching
tests + per-tool argument extraction tests.
"""

from __future__ import annotations

import re

import pytest
from fdai.core.conversation.coordinator import (
    _VERB_PATTERNS,
    _extract_query,
    _extract_tool_arguments,
)


def _match(text: str) -> tuple[str, str] | None:
    for pattern, tool_name in _VERB_PATTERNS:
        m = re.match(pattern, text, flags=re.IGNORECASE)
        if m:
            rest = m.group("rest") if "rest" in (m.groupdict() or {}) else ""
            return tool_name, _extract_query(rest)
    return None


# ---------------------------------------------------------------------------
# Verb -> tool routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utterance, expected_tool",
    [
        # query_operator_memory
        ("query_operator_memory resource-group rg/example", "query_operator_memory"),
        ("query operator memory resource rg/vm-a", "query_operator_memory"),
        ("operator_memory resource-group rg/x", "query_operator_memory"),
        # query_log
        ("query_log AzureActivity PT1H", "query_log"),
        ("query log AzureActivity PT1H", "query_log"),
        ("logs Errors PT1H", "query_log"),
        ("log Errors PT1H", "query_log"),
        # query_metric
        ("query_metric ns m Average PT5M", "query_metric"),
        ("query metric ns m Average PT5M", "query_metric"),
        ("metrics ns m Average PT5M", "query_metric"),
        ("metric ns m Average PT5M", "query_metric"),
        # query_deployments
        ("query_deployments P1D", "query_deployments"),
        ("query deployment P1D", "query_deployments"),
        ("list_deployments P1D", "query_deployments"),
        # correlate_incident
        ("correlate_incident INC-1", "correlate_incident"),
        ("correlate incident INC-1", "correlate_incident"),
        ("correlate INC-1", "correlate_incident"),
    ],
)
def test_read_verb_routes_to_expected_tool(utterance: str, expected_tool: str) -> None:
    result = _match(utterance)
    assert result is not None, f"no match for {utterance!r}"
    tool_name, _ = result
    assert tool_name == expected_tool


# ---------------------------------------------------------------------------
# query_operator_memory - argument extraction
# ---------------------------------------------------------------------------


class TestQueryOperatorMemoryArgs:
    def test_positional_scope_kind_and_ref(self) -> None:
        args = _extract_tool_arguments("query_operator_memory", "resource-group rg/example")
        assert args == {"scope_kind": "resource-group", "scope_ref": "rg/example"}

    def test_kv_overrides_positional(self) -> None:
        args = _extract_tool_arguments(
            "query_operator_memory",
            "positional-ignored scope_kind=resource scope_ref=rg/vm-a",
        )
        assert args["scope_kind"] == "resource"
        assert args["scope_ref"] == "rg/vm-a"

    def test_limit_coerced_to_int(self) -> None:
        args = _extract_tool_arguments(
            "query_operator_memory",
            "resource-group rg/x limit=5",
        )
        assert args["limit"] == 5

    def test_bad_limit_left_as_string(self) -> None:
        """A malformed limit is left as-is so the tool can surface a
        useful error rather than the coordinator hiding it."""

        args = _extract_tool_arguments(
            "query_operator_memory",
            "resource-group rg/x limit=abc",
        )
        assert args["limit"] == "abc"


# ---------------------------------------------------------------------------
# query_log - argument extraction
# ---------------------------------------------------------------------------


class TestQueryLogArgs:
    def test_kv_form(self) -> None:
        args = _extract_tool_arguments(
            "query_log",
            "query=AzureActivity window=PT1H max_rows=50",
        )
        assert args["query"] == "AzureActivity"
        assert args["window"] == "PT1H"
        assert args["max_rows"] == 50

    def test_positional_form(self) -> None:
        args = _extract_tool_arguments("query_log", "AzureActivity PT1H")
        # Last positional -> window; the rest -> query.
        assert args["window"] == "PT1H"
        assert args["query"] == "AzureActivity"

    def test_positional_multi_word_query(self) -> None:
        args = _extract_tool_arguments("query_log", "AzureActivity Errors PT1H")
        assert args["window"] == "PT1H"
        assert args["query"] == "AzureActivity Errors"

    def test_bad_max_rows_left_as_string(self) -> None:
        args = _extract_tool_arguments("query_log", "query=q window=PT1H max_rows=notanint")
        assert args["max_rows"] == "notanint"


# ---------------------------------------------------------------------------
# query_metric - argument extraction
# ---------------------------------------------------------------------------


class TestQueryMetricArgs:
    def test_kv_form(self) -> None:
        args = _extract_tool_arguments(
            "query_metric",
            "namespace=ns metric=PercentageCPU aggregation=Average window=PT5M",
        )
        assert args["namespace"] == "ns"
        assert args["metric"] == "PercentageCPU"
        assert args["aggregation"] == "Average"
        assert args["window"] == "PT5M"

    def test_positional_form(self) -> None:
        args = _extract_tool_arguments("query_metric", "ns metric-name Average PT5M")
        assert args["namespace"] == "ns"
        assert args["metric"] == "metric-name"
        assert args["aggregation"] == "Average"
        assert args["window"] == "PT5M"

    def test_kv_overrides_positional(self) -> None:
        args = _extract_tool_arguments(
            "query_metric",
            "ns m Average PT5M window=PT1H",
        )
        assert args["window"] == "PT1H"


# ---------------------------------------------------------------------------
# query_deployments - argument extraction
# ---------------------------------------------------------------------------


class TestQueryDeploymentsArgs:
    def test_kv_form(self) -> None:
        args = _extract_tool_arguments(
            "query_deployments",
            "window=P1D resource_ref=rg/vm-a",
        )
        assert args == {"window": "P1D", "resource_ref": "rg/vm-a"}

    def test_positional_form(self) -> None:
        args = _extract_tool_arguments("query_deployments", "P1D rg/vm-a")
        assert args["window"] == "P1D"
        assert args["resource_ref"] == "rg/vm-a"

    def test_window_only(self) -> None:
        args = _extract_tool_arguments("query_deployments", "P1D")
        assert args["window"] == "P1D"
        assert "resource_ref" not in args


# ---------------------------------------------------------------------------
# correlate_incident - argument extraction
# ---------------------------------------------------------------------------


class TestCorrelateIncidentArgs:
    def test_positional_id(self) -> None:
        args = _extract_tool_arguments("correlate_incident", "INC-1")
        assert args == {"incident_id": "INC-1"}

    def test_kv_id_overrides_positional(self) -> None:
        args = _extract_tool_arguments("correlate_incident", "IGNORED incident_id=INC-42")
        assert args["incident_id"] == "INC-42"

    def test_empty_query_returns_no_id(self) -> None:
        args = _extract_tool_arguments("correlate_incident", "")
        assert args == {}
