#!/usr/bin/env python3
"""Build a sanitized, proposal-only model lifecycle review record."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

_SCHEMA_VERSION = "fdai.model-lifecycle-proposal.v3"
_PROVIDER_FAILURES = frozenset({"ambiguous", "rate_limited", "unavailable", "unsupported_response"})
_CAPABILITY = re.compile(r"^(t1|t2)\.[a-z][a-z0-9._-]{1,63}$")


def reconcile_model_lifecycle(
    *,
    current: Mapping[str, object],
    candidate: Mapping[str, object] | None,
    deprecations: Sequence[Mapping[str, object]],
    provider_error: str | None = None,
) -> dict[str, object]:
    """Return deterministic review evidence without changing an active mapping."""
    source_models_digest = _mapping_digest(current)
    if provider_error is not None:
        reason = provider_error if provider_error in _PROVIDER_FAILURES else "provider_failure"
        return _base_result(
            status="abstained",
            reason=reason,
            source_models_digest=source_models_digest,
        )
    if candidate is None:
        return _base_result(
            status="abstained",
            reason="unavailable",
            source_models_digest=source_models_digest,
        )

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
    deprecated_families = {item["family"] for item in sanitized_deprecations}
    affected_capabilities = sorted(
        {str(change["capability"]) for change in changes}
        | {
            capability
            for capability, current_capability in current_capabilities.items()
            if current_capability.get("family") in deprecated_families
        }
    )

    status = "proposal" if changes or sanitized_deprecations else "no-change"
    result = _base_result(
        status=status,
        reason=None,
        source_models_digest=source_models_digest,
    )
    result["changes"] = changes
    result["deprecations"] = sanitized_deprecations
    result["compatibility_impact"] = sorted(compatibility)
    result["affected_capabilities"] = affected_capabilities
    if status == "proposal":
        result["proposal_digest"] = _proposal_digest(result)
    return result


def _base_result(
    *,
    status: str,
    reason: str | None,
    source_models_digest: str,
) -> dict[str, object]:
    result: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "status": status,
        "activation_authority": False,
        "source_models_digest": source_models_digest,
        "affected_capabilities": [],
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
            "source_models_digest": result["source_models_digest"],
            "affected_capabilities": result["affected_capabilities"],
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
        if not isinstance(name, str) or _CAPABILITY.fullmatch(name) is None:
            raise ValueError("resolved model capability name must be a bounded T1/T2 id")
        if name in indexed:
            raise ValueError("resolved model capability name must be unique")
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
        try:
            date.fromisoformat(retirement_date)
        except ValueError as exc:
            raise ValueError("retirement date must be an ISO 8601 calendar date") from exc
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


def _mapping_digest(value: Mapping[str, object]) -> str:
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
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
