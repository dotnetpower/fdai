#!/usr/bin/env python3
"""Freeze and verify one private deployment-owned configuration baseline."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import gzip
import hashlib
import io
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fdai.core.detection.configuration_drift import (
    DriftVerdict,
    FrozenConfigurationBaseline,
    compare_configuration,
)
from fdai.core.detection.configuration_drift_codec import baseline_from_dict
from fdai.delivery.azure.configuration_drift import (
    AzureArgConfigurationObservationSource,
    AzureBlobConfigurationBaselineConfig,
    AzureBlobConfigurationBaselineSource,
    AzureConfigurationObservationConfig,
)
from fdai.delivery.azure.dev_workload_identity import AsyncAzureCliWorkloadIdentity

_BINDING_ENV = "CONFIGURATION_BASELINE_BINDING_JSON"
_BASELINE_ENVELOPE_ENV = "CONFIGURATION_BASELINE_GZIP_BASE64"
_CONTAINER_ENV = "CONFIGURATION_BASELINE_CONTAINER_URL"
_MAX_BASELINE_BYTES = 16 * 1024 * 1024
_BINDING_KEYS = {
    "schema_version",
    "baseline_version",
    "baseline_sha256",
    "created_at",
    "document_sha256",
    "source",
    "scope",
    "subscription_scopes",
    "attribute_paths",
    "resource_count",
    "finding_count",
    "comparison_verdict",
    "arg_endpoint",
}
_SHA256_CHARS = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class BaselineBinding:
    """Strict deployment-owned metadata for one reviewed baseline."""

    baseline_version: str
    baseline_sha256: str
    created_at: datetime
    document_sha256: str
    source: str
    scope: str
    subscription_scopes: tuple[str, ...]
    attribute_paths: tuple[str, ...]
    resource_count: int
    finding_count: int
    comparison_verdict: str
    arg_endpoint: str
    digest: str

    @classmethod
    def from_environment(cls) -> BaselineBinding:
        raw_text = os.environ.get(_BINDING_ENV, "")
        if not raw_text:
            raise ValueError("configuration baseline binding is unavailable")
        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError("configuration baseline binding is not valid JSON") from exc
        if not isinstance(raw, Mapping):
            raise ValueError("configuration baseline binding MUST be one JSON object")
        unknown = set(raw).difference(_BINDING_KEYS)
        missing = _BINDING_KEYS.difference(raw)
        if unknown or missing:
            raise ValueError("configuration baseline binding fields are invalid")
        if raw["schema_version"] != "fdai.configuration-baseline-binding.v1":
            raise ValueError("configuration baseline binding schema version is unsupported")
        baseline_sha256 = _digest(raw, "baseline_sha256")
        document_sha256 = _digest(raw, "document_sha256")
        version = _text(raw, "baseline_version")
        source = _text(raw, "source")
        scope = _text(raw, "scope")
        created_at = _timestamp(raw, "created_at")
        subscriptions = _string_tuple(raw, "subscription_scopes")
        attribute_paths = _string_tuple(raw, "attribute_paths")
        resource_count = _positive_integer(raw, "resource_count")
        finding_count = _positive_integer(raw, "finding_count")
        verdict = _text(raw, "comparison_verdict")
        if verdict != DriftVerdict.PASSED.value:
            raise ValueError("reviewed configuration baseline verdict MUST be passed")
        arg_endpoint = _text(raw, "arg_endpoint")
        canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        return cls(
            baseline_version=version,
            baseline_sha256=baseline_sha256,
            created_at=created_at,
            document_sha256=document_sha256,
            source=source,
            scope=scope,
            subscription_scopes=subscriptions,
            attribute_paths=attribute_paths,
            resource_count=resource_count,
            finding_count=finding_count,
            comparison_verdict=verdict,
            arg_endpoint=arg_endpoint,
            digest=hashlib.sha256(canonical).hexdigest(),
        )

    @property
    def blob_url(self) -> str:
        container_url = os.environ.get(_CONTAINER_ENV, "").strip().rstrip("/")
        if not container_url:
            raise ValueError("configuration baseline container is unavailable")
        value = f"{container_url}/configuration-baselines/{self.baseline_sha256}.json"
        AzureBlobConfigurationBaselineConfig(
            blob_url=value,
            expected_sha256=self.baseline_sha256,
        )
        return value

    def observation_config(self) -> AzureConfigurationObservationConfig:
        return AzureConfigurationObservationConfig(
            allowed_scope=self.scope,
            subscription_scopes=self.subscription_scopes,
            attribute_paths=self.attribute_paths,
            arg_endpoint=self.arg_endpoint,
        )


def prepare(*, baseline_path: Path, tfvars_path: Path) -> None:
    """Decode the approved baseline envelope and write private runner files."""

    binding = BaselineBinding.from_environment()
    baseline, payload = _approved_baseline(binding)
    baseline_path.write_bytes(payload)
    baseline_path.chmod(0o600)
    if tfvars_path.is_file():
        tfvars = json.loads(tfvars_path.read_text(encoding="utf-8"))
        if not isinstance(tfvars, dict) or "configuration_drift" in tfvars:
            raise RuntimeError("service tfvars cannot accept configuration drift binding")
    else:
        tfvars = {}
    tfvars["configuration_drift"] = {
        "enabled": True,
        "baseline_url": binding.blob_url,
        "baseline_version": binding.baseline_version,
        "baseline_sha256": binding.baseline_sha256,
        "scope": binding.scope,
        "subscription_scopes": list(binding.subscription_scopes),
        "attribute_paths": list(binding.attribute_paths),
        "arg_endpoint": binding.arg_endpoint,
    }
    tfvars_path.write_text(
        json.dumps(tfvars, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    tfvars_path.chmod(0o600)


async def receipt(*, output_path: Path) -> None:
    """Read the frozen Blob independently and compare it with current ARG state."""

    binding = BaselineBinding.from_environment()
    identity = AsyncAzureCliWorkloadIdentity.from_env()
    async with httpx.AsyncClient() as client:
        baseline = await AzureBlobConfigurationBaselineSource(
            identity=identity,
            http_client=client,
            config=AzureBlobConfigurationBaselineConfig(
                blob_url=binding.blob_url,
                expected_sha256=binding.baseline_sha256,
            ),
        ).load()
        observation = await AzureArgConfigurationObservationSource(
            identity=identity,
            http_client=client,
            config=binding.observation_config(),
        ).observe(scope=binding.scope)
    if len(baseline.resources) != binding.resource_count:
        raise RuntimeError("deployed configuration baseline resource count is invalid")
    report = compare_configuration(baseline, observation)
    failed_findings = sum(finding.verdict is not DriftVerdict.PASSED for finding in report.findings)
    sanitized = {
        "schema_version": "fdai.configuration-drift-live-receipt.v1",
        "baseline_identity": {
            "version": baseline.version,
            "baseline_sha256": baseline.sha256,
            "document_sha256": baseline.document_sha256,
            "binding_sha256": binding.digest,
        },
        "scope_sha256": hashlib.sha256(binding.scope.encode()).hexdigest(),
        "observed_at": observation.observed_at.isoformat(),
        "completeness": observation.completeness.value,
        "verdict": report.verdict.value,
        "baseline_resource_count": len(baseline.resources),
        "resource_count": len(observation.resources),
        "finding_count": len(report.findings),
        "failed_finding_count": failed_findings,
        "mutation_count": report.mutation_count,
        "approval_request_count": report.approval_request_count,
        "mitigation_execution_count": report.mitigation_execution_count,
        "unsupported_claim_count": report.unsupported_claim_count,
    }
    output_path.write_text(
        json.dumps(sanitized, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def verify_runtime(*, app_path: Path) -> None:
    """Verify the deployed Core revision carries the exact private binding."""

    binding = BaselineBinding.from_environment()
    raw = json.loads(app_path.read_text(encoding="utf-8"))
    containers = raw.get("properties", {}).get("template", {}).get("containers", [])
    core = next(
        (
            item
            for item in containers
            if isinstance(item, Mapping) and item.get("name") == "core-control-plane"
        ),
        None,
    )
    if not isinstance(core, Mapping):
        raise RuntimeError("deployed Core container configuration is unavailable")
    env_items = core.get("env")
    if not isinstance(env_items, list):
        raise RuntimeError("deployed Core environment is unavailable")
    deployed = {
        item.get("name"): item.get("value")
        for item in env_items
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
        and "secretRef" not in item
    }
    expected = {
        "FDAI_CONFIGURATION_DRIFT_ENABLED": "1",
        "FDAI_CONFIGURATION_BASELINE_URL": binding.blob_url,
        "FDAI_CONFIGURATION_BASELINE_VERSION": binding.baseline_version,
        "FDAI_CONFIGURATION_BASELINE_SHA256": binding.baseline_sha256,
        "FDAI_CONFIGURATION_SCOPE": binding.scope,
        "FDAI_CONFIGURATION_SUBSCRIPTIONS_JSON": json.dumps(
            binding.subscription_scopes,
            separators=(",", ":"),
        ),
        "FDAI_CONFIGURATION_ATTRIBUTE_PATHS_JSON": json.dumps(
            binding.attribute_paths,
            separators=(",", ":"),
        ),
        "FDAI_CONFIGURATION_ARG_ENDPOINT": binding.arg_endpoint,
    }
    if any(deployed.get(key) != value for key, value in expected.items()):
        raise RuntimeError("deployed Core configuration drift binding does not match review")


def _approved_baseline(
    binding: BaselineBinding,
) -> tuple[FrozenConfigurationBaseline, bytes]:
    encoded = os.environ.get(_BASELINE_ENVELOPE_ENV, "")
    if not encoded:
        raise ValueError("configuration baseline envelope is unavailable")
    try:
        compressed = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("configuration baseline envelope is not valid base64") from exc
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            raw = stream.read(_MAX_BASELINE_BYTES + 1)
    except (gzip.BadGzipFile, EOFError, OSError) as exc:
        raise ValueError("configuration baseline envelope is not valid gzip") from exc
    if not raw or len(raw) > _MAX_BASELINE_BYTES:
        raise ValueError("configuration baseline envelope size is outside the allowed range")
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("configuration baseline envelope is not valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("configuration baseline envelope MUST contain one JSON object")
    baseline = baseline_from_dict(decoded)
    if (
        baseline.version != binding.baseline_version
        or baseline.sha256 != binding.baseline_sha256
        or baseline.document_sha256 != binding.document_sha256
        or baseline.scope != binding.scope
        or baseline.source != binding.source
        or baseline.created_at != binding.created_at
        or len(baseline.resources) != binding.resource_count
    ):
        raise RuntimeError("configuration baseline envelope does not match review")
    payload = json.dumps(
        baseline.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    if hashlib.sha256(payload).hexdigest() != binding.baseline_sha256:
        raise RuntimeError("configuration baseline byte digest is not canonical")
    return baseline, payload


def _text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"configuration baseline binding {key} is invalid")
    return value.strip()


def _digest(raw: Mapping[str, Any], key: str) -> str:
    value = _text(raw, key)
    if len(value) != 64 or any(char not in _SHA256_CHARS for char in value):
        raise ValueError(f"configuration baseline binding {key} is invalid")
    return value


def _timestamp(raw: Mapping[str, Any], key: str) -> datetime:
    try:
        value = datetime.fromisoformat(_text(raw, key).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"configuration baseline binding {key} is invalid") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"configuration baseline binding {key} is invalid")
    return value


def _string_tuple(raw: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"configuration baseline binding {key} is invalid")
    normalized = tuple(item.strip() for item in value if isinstance(item, str))
    if (
        len(normalized) != len(value)
        or any(not item for item in normalized)
        or normalized != tuple(sorted(set(normalized)))
    ):
        raise ValueError(f"configuration baseline binding {key} is invalid")
    return normalized


def _positive_integer(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"configuration baseline binding {key} is invalid")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--baseline", type=Path, required=True)
    prepare_parser.add_argument("--tfvars", type=Path, required=True)
    receipt_parser = commands.add_parser("receipt")
    receipt_parser.add_argument("--output", type=Path, required=True)
    runtime_parser = commands.add_parser("verify-runtime")
    runtime_parser.add_argument("--app", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "prepare":
        prepare(baseline_path=args.baseline, tfvars_path=args.tfvars)
    elif args.command == "receipt":
        asyncio.run(receipt(output_path=args.output))
    else:
        verify_runtime(app_path=args.app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
