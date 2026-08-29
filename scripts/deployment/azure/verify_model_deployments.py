#!/usr/bin/env python3
"""Verify Azure OpenAI deployments against one sealed resolved-model artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "fdai.model-deployment-readback.v1"
_MAX_INPUT_BYTES = 2 * 1024 * 1024


class ModelDeploymentVerificationError(RuntimeError):
    """The provider readback does not match the sealed model deployment intent."""


def verify_model_deployments(
    resolved_path: Path,
    provider_path: Path,
    output_path: Path,
    *,
    capability_names: frozenset[str] | None = None,
) -> dict[str, object]:
    """Compare provider model properties and write a sanitized canonical receipt."""
    resolved = _load_object(resolved_path, "resolved-model artifact")
    provider = _load_object(provider_path, "provider deployment readback")
    capabilities = resolved.get("capabilities")
    deployments = provider.get("value")
    if not isinstance(capabilities, list) or not isinstance(deployments, list):
        raise ModelDeploymentVerificationError("model deployment evidence arrays are invalid")

    expected = _expected_capabilities(capabilities)
    if capability_names:
        missing = capability_names.difference(expected)
        if missing:
            raise ModelDeploymentVerificationError(
                "selected resolved capability is unavailable: " + ", ".join(sorted(missing))
            )
        expected = {name: expected[name] for name in sorted(capability_names)}
    observed = _observed_deployments(deployments)
    verified: list[dict[str, object]] = []
    for name in sorted(expected):
        wanted = expected[name]
        actual = observed.get(name)
        if actual is None:
            raise ModelDeploymentVerificationError(f"provider deployment is missing: {name}")
        if actual != wanted:
            raise ModelDeploymentVerificationError(f"provider deployment does not match: {name}")
        verified.append({"capability": name, **actual})

    receipt: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "resolved_models_digest": hashlib.sha256(resolved_path.read_bytes()).hexdigest(),
        "verified_deployments": verified,
    }
    canonical = json.dumps(receipt, separators=(",", ":"), sort_keys=True)
    receipt["receipt_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    output_path.write_text(
        json.dumps(receipt, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return receipt


def _expected_capabilities(values: list[object]) -> dict[str, dict[str, object]]:
    expected: dict[str, dict[str, object]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise ModelDeploymentVerificationError("resolved capability is invalid")
        if value.get("status") == "hil-only":
            continue
        name = _required_string(value, "name", "resolved capability")
        if name in expected:
            raise ModelDeploymentVerificationError(f"resolved capability is duplicated: {name}")
        unit = value.get("capacity_unit", "tpm")
        if unit == "ptu":
            capacity = _positive_int(value.get("capacity_value"), "resolved PTU capacity")
        elif unit == "tpm":
            capacity_tpm = _positive_int(value.get("capacity_tpm"), "resolved TPM capacity")
            if capacity_tpm < 1000 or capacity_tpm % 1000 != 0:
                raise ModelDeploymentVerificationError(
                    "resolved TPM capacity must use complete 1000-token units"
                )
            capacity = capacity_tpm // 1000
        else:
            raise ModelDeploymentVerificationError("resolved capacity unit is invalid")
        expected[name] = {
            "family": _required_string(value, "family", "resolved capability"),
            "version": _required_string(value, "version", "resolved capability"),
            "sku": _required_string(value, "sku", "resolved capability"),
            "capacity": capacity,
            "provisioning_state": "Succeeded",
        }
    if not expected:
        raise ModelDeploymentVerificationError("resolved artifact has no deployable capability")
    return expected


def _observed_deployments(values: list[object]) -> dict[str, dict[str, object]]:
    observed: dict[str, dict[str, object]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise ModelDeploymentVerificationError("provider deployment is invalid")
        name = _required_string(value, "name", "provider deployment")
        if name in observed:
            raise ModelDeploymentVerificationError(f"provider deployment is duplicated: {name}")
        properties = value.get("properties")
        sku = value.get("sku")
        if not isinstance(properties, dict) or not isinstance(sku, dict):
            raise ModelDeploymentVerificationError("provider deployment shape is invalid")
        model = properties.get("model")
        if not isinstance(model, dict):
            raise ModelDeploymentVerificationError("provider deployment model is invalid")
        observed[name] = {
            "family": _required_string(model, "name", "provider model"),
            "version": _required_string(model, "version", "provider model"),
            "sku": _required_string(sku, "name", "provider deployment SKU"),
            "capacity": _positive_int(sku.get("capacity"), "provider deployment capacity"),
            "provisioning_state": _required_string(
                properties, "provisioningState", "provider deployment"
            ),
        }
    return observed


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise ModelDeploymentVerificationError(f"{label} is unavailable or too large")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelDeploymentVerificationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ModelDeploymentVerificationError(f"{label} must be an object")
    return value


def _required_string(value: dict[str, Any], key: str, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ModelDeploymentVerificationError(f"{label} {key} is invalid")
    return item


def _positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ModelDeploymentVerificationError(f"{label} is invalid")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolved", type=Path, required=True)
    parser.add_argument("--provider", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--capabilities", default="")
    args = parser.parse_args()
    try:
        selected = frozenset(filter(None, args.capabilities.split(",")))
        verify_model_deployments(
            args.resolved,
            args.provider,
            args.out,
            capability_names=selected or None,
        )
    except (OSError, ModelDeploymentVerificationError) as exc:
        print(f"model deployment verification failed: {exc}")
        return 1
    print("verified model deployment readback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
