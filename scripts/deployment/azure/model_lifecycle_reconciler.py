#!/usr/bin/env python3
"""Build a sanitized, proposal-only model lifecycle review record."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

_SCHEMA_VERSION = "fdai.model-lifecycle-proposal.v2"
_PROVIDER_FAILURES = frozenset({"ambiguous", "rate_limited", "unavailable", "unsupported_response"})


def reconcile_model_lifecycle(
    *,
    current: Mapping[str, object],
    candidate: Mapping[str, object] | None,
    deprecations: Sequence[Mapping[str, object]],
    provider_error: str | None = None,
) -> dict[str, object]:
    """Return deterministic review evidence without changing an active mapping."""
    if provider_error is not None:
        reason = provider_error if provider_error in _PROVIDER_FAILURES else "provider_failure"
        return _base_result(status="abstained", reason=reason)
    if candidate is None:
        return _base_result(status="abstained", reason="unavailable")

    current_capabilities = _capability_index(current)
    candidate_capabilities = _capability_index(candidate)
    changes: list[dict[str, object]] = []
    compatibility: set[str] = set()
    for capability in sorted(current_capabilities.keys() | candidate_capabilities.keys()):
        previous = current_capabilities.get(capability, {})
        proposed = candidate_capabilities.get(capability, {})
        if previous == proposed:
            continue
        change = {
            "capability": capability,
            "current_family": previous.get("family"),
            "current_publisher": previous.get("publisher"),
            "current_sku": previous.get("sku"),
            "current_capacity_unit": previous.get("capacity_unit"),
            "current_capacity_value": previous.get("capacity_value"),
            "proposed_family": proposed.get("family"),
            "proposed_publisher": proposed.get("publisher"),
            "proposed_sku": proposed.get("sku"),
            "proposed_capacity_unit": proposed.get("capacity_unit"),
            "proposed_capacity_value": proposed.get("capacity_value"),
            "proposed_status": proposed.get("status", "unavailable"),
        }
        changes.append(change)
        if previous.get("family") != proposed.get("family"):
            compatibility.add("model_family_change")
        if previous.get("publisher") != proposed.get("publisher"):
            compatibility.add("publisher_change")
        if previous.get("sku") != proposed.get("sku"):
            compatibility.add("sku_change")
        if (
            previous.get("capacity_unit"),
            previous.get("capacity_value"),
        ) != (
            proposed.get("capacity_unit"),
            proposed.get("capacity_value"),
        ):
            compatibility.add("capacity_change")
        if proposed.get("status") not in {"resolved", "capacity-reduced"}:
            compatibility.add("capability_degradation")

    current_families = {
        value.get("family")
        for value in current_capabilities.values()
        if isinstance(value.get("family"), str)
    }
    sanitized_deprecations = _sanitize_deprecations(deprecations, current_families)
    if sanitized_deprecations:
        compatibility.add("current_family_deprecated")

    status = "proposal" if changes or sanitized_deprecations else "no-change"
    result = _base_result(status=status, reason=None)
    result["changes"] = changes
    result["deprecations"] = sanitized_deprecations
    result["compatibility_impact"] = sorted(compatibility)
    if status == "proposal":
        result["proposal_digest"] = _proposal_digest(result)
    return result


def _base_result(*, status: str, reason: str | None) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": status,
        "activation_authority": False,
        "changes": [],
        "deprecations": [],
        "compatibility_impact": [],
        "proposal_digest": None,
    }
    if reason is not None:
        result["reason"] = reason
        ordered = {
            "schema_version": result["schema_version"],
            "status": result["status"],
            "reason": result["reason"],
            "activation_authority": result["activation_authority"],
            "changes": result["changes"],
            "deprecations": result["deprecations"],
            "compatibility_impact": result["compatibility_impact"],
            "proposal_digest": result["proposal_digest"],
        }
        return ordered
    return result


def _capability_index(payload: Mapping[str, object]) -> dict[str, dict[str, object]]:
    raw_capabilities = payload.get("capabilities")
    if not isinstance(raw_capabilities, list) or not raw_capabilities:
        raise ValueError("resolved model capabilities must be a non-empty array")
    indexed: dict[str, dict[str, object]] = {}
    for raw in raw_capabilities:
        if not isinstance(raw, Mapping):
            raise ValueError("resolved model capability must be an object")
        name = raw.get("name")
        if not isinstance(name, str) or not name or name in indexed:
            raise ValueError("resolved model capability name must be unique and non-empty")
        indexed[name] = {
            "family": _optional_string(raw.get("family")),
            "publisher": _optional_string(raw.get("publisher")),
            "sku": _optional_string(raw.get("sku")),
            **_capacity(raw),
            "status": _required_string(raw.get("status"), "capability status"),
        }
    return indexed


def _capacity(raw: Mapping[str, object]) -> dict[str, object]:
    unit = raw.get("capacity_unit", "tpm")
    if unit not in {"tpm", "ptu"}:
        raise ValueError("capability capacity unit must be tpm or ptu")
    key = "capacity_value" if unit == "ptu" else "capacity_tpm"
    value = raw.get(key)
    if value is None:
        return {"capacity_unit": unit, "capacity_value": None}
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("capability capacity value must be a non-negative integer")
    return {"capacity_unit": unit, "capacity_value": value}


def _sanitize_deprecations(
    deprecations: Sequence[Mapping[str, object]],
    current_families: set[object],
) -> list[dict[str, str]]:
    sanitized: dict[tuple[str, str], dict[str, str]] = {}
    for raw in deprecations:
        family = _required_string(raw.get("family"), "deprecation family")
        retirement_date = _required_string(raw.get("retirement_date"), "retirement date")
        if family not in current_families:
            continue
        sanitized[(family, retirement_date)] = {
            "family": family,
            "retirement_date": retirement_date,
        }
    return [sanitized[key] for key in sorted(sanitized)]


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _required_string(value, "capability field")


def _proposal_digest(result: Mapping[str, object]) -> str:
    digest_input = dict(result)
    digest_input["proposal_digest"] = None
    canonical = json.dumps(digest_input, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _load_mapping(path: Path) -> Mapping[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _load_deprecations(path: Path | None) -> Sequence[Mapping[str, object]]:
    if path is None:
        return ()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return loaded


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--deprecations", type=Path)
    parser.add_argument("--provider-error", choices=sorted(_PROVIDER_FAILURES))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = reconcile_model_lifecycle(
            current=_load_mapping(args.current),
            candidate=_load_mapping(args.candidate) if args.candidate else None,
            deprecations=_load_deprecations(args.deprecations),
            provider_error=args.provider_error,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"model-lifecycle-reconciler: {type(exc).__name__}", file=sys.stderr)
        return 2
    args.out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "reconcile_model_lifecycle"]
