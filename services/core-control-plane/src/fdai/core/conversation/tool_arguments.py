"""Deterministic argument parsing for conversation tools."""

from __future__ import annotations

import json
from typing import Any


def extract_tool_arguments(tool_name: str, query: str) -> dict[str, Any]:
    """Map a raw query string onto the argument shape for one tool."""

    if tool_name == "explore_catalog":
        return {"query": query} if query else {"query": ""}
    if tool_name == "search_tools":
        search_args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "query" not in search_args:
            search_args["query"] = " ".join(positional)
        return search_args
    if tool_name == "describe_tool":
        return {"tool_name": query}
    if tool_name == "describe_event":
        args: dict[str, Any] = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "resource_type" not in args and positional:
            args["resource_type"] = positional[0]
        if "resource_id" not in args and len(positional) >= 2:
            args["resource_id"] = positional[1]
        return args
    if tool_name == "explain_verdict":
        return {"event_id": query}
    if tool_name == "query_audit":
        return parse_kv_tokens(query)
    if tool_name == "query_inventory":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "resource_type" not in args and positional:
            args["resource_type"] = positional[0]
        if "id_substring" not in args and len(positional) >= 2:
            args["id_substring"] = positional[1]
        return args
    if tool_name == "query_operator_memory":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "scope_kind" not in args and positional:
            args["scope_kind"] = positional[0]
        if "scope_ref" not in args and len(positional) >= 2:
            args["scope_ref"] = positional[1]
        if "limit" in args:
            try:
                args["limit"] = int(args["limit"])
            except (TypeError, ValueError):
                pass
        return args
    if tool_name == "query_log":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "window" not in args and positional:
            args["window"] = positional[-1]
        if "query" not in args and len(positional) >= 2:
            args["query"] = " ".join(positional[:-1])
        if "max_rows" in args:
            try:
                args["max_rows"] = int(args["max_rows"])
            except (TypeError, ValueError):
                pass
        return args
    if tool_name == "query_metric":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        for index, key in enumerate(("namespace", "metric", "aggregation", "window")):
            if key not in args and len(positional) > index:
                args[key] = positional[index]
        return args
    if tool_name == "query_deployments":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "window" not in args and positional:
            args["window"] = positional[0]
        if "resource_ref" not in args and len(positional) >= 2:
            args["resource_ref"] = positional[1]
        return args
    if tool_name == "correlate_incident":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "incident_id" not in args and positional:
            args["incident_id"] = positional[0]
        if "incident_id" not in args and query.strip():
            args["incident_id"] = query.strip()
        return args
    if tool_name == "simulate_change":
        args = {}
        stripped = query.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                scenario = json.loads(stripped)
                if isinstance(scenario, dict):
                    return {"scenario": scenario}
            except json.JSONDecodeError:
                pass
        kv = parse_kv_tokens(query)
        if kv:
            scenario_dict: dict[str, Any] = {
                key: value for key, value in kv.items() if key != "signal_type"
            }
            if scenario_dict:
                args["scenario"] = scenario_dict
            if "signal_type" in kv:
                args["signal_type"] = kv["signal_type"]
        return args
    if tool_name == "list_hil":
        args = parse_kv_tokens(query)
        if "limit" in args:
            try:
                args["limit"] = int(args["limit"])
            except (TypeError, ValueError):
                pass
        return args
    if tool_name == "approve_hil":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "idempotency_key" not in args and positional:
            args["idempotency_key"] = positional[0]
        if "decision" not in args and len(positional) >= 2:
            args["decision"] = positional[1]
        if "justification" not in args and len(positional) >= 3:
            args["justification"] = " ".join(positional[2:])
        return args
    if tool_name == "run_runbook":
        args = parse_kv_tokens(query)
        positional = [token for token in query.split() if "=" not in token]
        if "name" not in args and positional:
            args["name"] = positional[0]
        if "dry_run" in args:
            raw = str(args["dry_run"]).lower()
            args["dry_run"] = raw in ("true", "1", "yes", "y")
        if "params_json" in args:
            try:
                loaded = json.loads(args.pop("params_json"))
                if isinstance(loaded, dict):
                    args["params"] = loaded
            except json.JSONDecodeError:
                pass
        return args
    if tool_name == "activate_break_glass":
        args = parse_kv_tokens(query)
        if "expiry_seconds" in args:
            try:
                args["expiry_seconds"] = int(args["expiry_seconds"])
            except (TypeError, ValueError):
                pass
        if "reason" not in args and query.strip():
            leftover = " ".join(token for token in query.split() if "=" not in token)
            if leftover:
                args["reason"] = leftover
        return args
    return {}


def parse_kv_tokens(query: str) -> dict[str, Any]:
    """Parse whitespace-separated ``key=value`` tokens."""

    result: dict[str, Any] = {}
    for token in query.split():
        if "=" not in token:
            continue
        key, _, value = token.partition("=")
        key = key.strip()
        if not key:
            continue
        parsed = value.strip()
        if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {'"', "'"}:
            parsed = parsed[1:-1]
        result[key] = parsed
    return result
