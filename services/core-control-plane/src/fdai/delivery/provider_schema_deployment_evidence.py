"""Verify one deployed provider-schema Job against durable runtime evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.provider_schema import ProviderSchemaError
from fdai.delivery.provider_schema_ledger import ProviderSchemaLedger
from fdai.delivery.provider_schema_state_ledger import StateStoreProviderSchemaLedger
from fdai.shared.providers.state_store import StateStore

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLAN_ID = re.compile(r"^plan-[1-9][0-9]*-[1-9][0-9]*$")
_EXECUTION_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,127}$")


class ProviderSchemaAuditReader(Protocol):
    """Read bounded Saga audit evidence for one exact correlation."""

    async def list_incident_evidence(
        self,
        *,
        correlation_id: str,
        limit: int,
    ) -> tuple[tuple[Mapping[str, object], ...], bool]: ...


async def collect_provider_schema_deployment_evidence(
    *,
    store: StateStore,
    audit_reader: ProviderSchemaAuditReader,
    ledger_root: Path,
    application_source_commit: str,
    runtime_image_revision: str,
    plan_id: str,
    execution_name: str,
    execution_status: str,
    started_at: datetime,
    audit_attempts: int = 10,
    audit_interval_seconds: float = 3.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, object]:
    """Return sanitized evidence or fail closed on stale or incomplete records."""

    _validate_context(
        application_source_commit=application_source_commit,
        runtime_image_revision=runtime_image_revision,
        plan_id=plan_id,
        execution_name=execution_name,
        execution_status=execution_status,
        started_at=started_at,
        audit_attempts=audit_attempts,
        audit_interval_seconds=audit_interval_seconds,
    )
    ledger_root.mkdir(parents=True, exist_ok=True)
    generation = await StateStoreProviderSchemaLedger(store).hydrate_generation(ledger_root)
    if generation is None:
        raise ProviderSchemaError("provider schema durable generation is unavailable")
    receipt = ProviderSchemaLedger(ledger_root).read_last_run("azure")
    if receipt is None:
        raise ProviderSchemaError("provider schema durable run receipt is unavailable")
    if receipt.get("provider") != "azure" or receipt.get("grants_authority") is not False:
        raise ProviderSchemaError("provider schema durable run receipt identity is invalid")
    checked_at = _receipt_time(receipt)
    if checked_at < started_at.astimezone(UTC):
        raise ProviderSchemaError("provider schema durable run receipt predates Job execution")
    if receipt.get("stale") is not False:
        raise ProviderSchemaError("provider schema durable run receipt is stale")
    source_revision = _required_text(receipt, "source_revision", _SOURCE_REVISION)
    baseline_digest = _required_text(receipt, "baseline_digest", _SHA256)
    observed_digest = _required_text(receipt, "observed_digest", _SHA256)
    disposition = _required_text(receipt, "disposition")
    raw_drift_digest = receipt.get("drift_digest")
    if raw_drift_digest is not None and (
        not isinstance(raw_drift_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", raw_drift_digest) is None
    ):
        raise ProviderSchemaError("provider schema run receipt drift_digest is invalid")
    drift_digest = raw_drift_digest
    review_required = receipt.get("review_required") is True
    review_status = "not_applicable"
    correlation_id: str | None = None
    review_package_digest: str | None = None
    verdict: Mapping[str, object] | None = None
    audit_entry_hash: str | None = None

    if review_required:
        if receipt.get("review_dispatched") is not True:
            raise ProviderSchemaError("provider schema Heimdall review was not dispatched")
        if receipt.get("review_handoff_reason") is not None:
            raise ProviderSchemaError("provider schema Heimdall review handoff is incomplete")
        review_package_digest = _required_text(receipt, "review_package_digest", _SHA256)
        drift_digest = _required_text(receipt, "drift_digest", re.compile(r"^[0-9a-f]{64}$"))
        correlation_id = f"provider-schema:azure:{drift_digest}"
        verdict, audit_entry_hash = await _wait_for_saga_verdict(
            audit_reader,
            correlation_id=correlation_id,
            drift_digest=drift_digest,
            attempts=audit_attempts,
            interval_seconds=audit_interval_seconds,
            sleep=sleep,
        )
        review_status = "verified"
    elif (
        receipt.get("review_dispatched") is not False
        or receipt.get("review_package_digest") is not None
        or receipt.get("review_handoff_reason") is not None
    ):
        raise ProviderSchemaError("provider schema no-review receipt is inconsistent")

    receipt_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest()
    )
    return {
        "schema_version": "fdai.provider-schema-deployment-evidence.v1",
        "application_source_commit": application_source_commit,
        "runtime_image_revision": runtime_image_revision,
        "plan_id": plan_id,
        "job_execution_ref_digest": hashlib.sha256(execution_name.encode()).hexdigest(),
        "job_execution_status": execution_status,
        "checked_at": checked_at.isoformat(),
        "provider_source_revision": source_revision,
        "baseline_digest": baseline_digest,
        "observed_digest": observed_digest,
        "drift_digest": drift_digest,
        "disposition": disposition,
        "durable_generation_digest": generation.generation_digest,
        "durable_generation_revision": generation.revision,
        "run_receipt_digest": receipt_digest,
        "review_package_digest": review_package_digest,
        "heimdall_review_dispatched": receipt.get("review_dispatched") is True,
        "review_evidence_status": review_status,
        "correlation_id": correlation_id,
        "forseti_risk_verdict": None if verdict is None else verdict["risk_verdict"],
        "forseti_reason": None if verdict is None else verdict["reason"],
        "saga_audit_entry_hash": audit_entry_hash,
        "grants_authority": False,
    }


def _validate_context(
    *,
    application_source_commit: str,
    runtime_image_revision: str,
    plan_id: str,
    execution_name: str,
    execution_status: str,
    started_at: datetime,
    audit_attempts: int,
    audit_interval_seconds: float,
) -> None:
    if not _SHA40.fullmatch(application_source_commit):
        raise ValueError("application source commit is invalid")
    if not _SHA40.fullmatch(runtime_image_revision):
        raise ValueError("runtime image revision is invalid")
    if not _PLAN_ID.fullmatch(plan_id):
        raise ValueError("provider schema plan id is invalid")
    if not _EXECUTION_NAME.fullmatch(execution_name):
        raise ValueError("provider schema Job execution name is invalid")
    if execution_status != "Succeeded":
        raise ProviderSchemaError("provider schema Job execution did not succeed")
    if started_at.tzinfo is None:
        raise ValueError("provider schema Job start time MUST be timezone-aware")
    if audit_attempts < 1 or audit_interval_seconds < 0:
        raise ValueError("provider schema audit polling bounds are invalid")


def _receipt_time(receipt: Mapping[str, object]) -> datetime:
    raw = receipt.get("checked_at")
    if not isinstance(raw, str):
        raise ProviderSchemaError("provider schema run receipt time is invalid")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderSchemaError("provider schema run receipt time is invalid") from exc
    if parsed.tzinfo is None:
        raise ProviderSchemaError("provider schema run receipt time MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _required_text(
    source: Mapping[str, object],
    key: str,
    pattern: re.Pattern[str] | None = None,
) -> str:
    value = source.get(key)
    invalid_pattern = (
        isinstance(value, str) and pattern is not None and not pattern.fullmatch(value)
    )
    if not isinstance(value, str) or not value or invalid_pattern:
        raise ProviderSchemaError(f"provider schema run receipt {key} is invalid")
    return value


async def _wait_for_saga_verdict(
    reader: ProviderSchemaAuditReader,
    *,
    correlation_id: str,
    drift_digest: str,
    attempts: int,
    interval_seconds: float,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[Mapping[str, object], str]:
    for attempt in range(attempts):
        rows, truncated = await reader.list_incident_evidence(
            correlation_id=correlation_id,
            limit=50,
        )
        if truncated:
            raise ProviderSchemaError("provider schema Saga audit evidence exceeds bound")
        for row in rows:
            matched = _provider_schema_verdict(row, correlation_id, drift_digest)
            if matched is not None:
                return matched
        if attempt + 1 < attempts:
            await sleep(interval_seconds)
    raise ProviderSchemaError("provider schema Forseti verdict and Saga audit are unavailable")


def _provider_schema_verdict(
    row: Mapping[str, object],
    correlation_id: str,
    drift_digest: str,
) -> tuple[Mapping[str, object], str] | None:
    entry = row.get("entry")
    if not isinstance(entry, Mapping):
        return None
    payload = entry.get("payload")
    if not isinstance(payload, Mapping):
        return None
    expected_idempotency_key = f"provider-schema-drift:{drift_digest}"
    if not (
        row.get("mode") == "shadow"
        and entry.get("principal") == "Forseti"
        and entry.get("topic") == "object.verdict"
        and entry.get("correlation_id") == correlation_id
        and payload.get("producer_principal") == "Forseti"
        and payload.get("correlation_id") == correlation_id
        and payload.get("idempotency_key") == expected_idempotency_key
        and payload.get("resource_id") == "provider-schema://azure"
        and payload.get("action_type") == ""
        and payload.get("risk_verdict") == "hil"
        and payload.get("reason") == "no_rule_match"
    ):
        return None
    entry_hash = entry.get("entry_hash")
    if not isinstance(entry_hash, str) or re.fullmatch(r"[0-9a-f]{64}", entry_hash) is None:
        raise ProviderSchemaError("provider schema Saga audit hash is invalid")
    return payload, entry_hash


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-provider-schema-deployment-evidence")
    parser.add_argument("--application-source-commit", required=True)
    parser.add_argument("--runtime-image-revision", required=True)
    parser.add_argument("--plan-id", required=True)
    parser.add_argument("--execution-name", required=True)
    parser.add_argument("--execution-status", required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Verify deployment evidence using the DSN supplied only through the environment."""

    args = _parser().parse_args(argv)
    dsn = os.environ.get("FDAI_PROVIDER_SCHEMA_DSN", "").strip()
    if not dsn:
        print("error: FDAI_PROVIDER_SCHEMA_DSN is required", file=sys.stderr)
        return 2
    try:
        started_at = datetime.fromisoformat(args.started_at.replace("Z", "+00:00"))
        store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
        with tempfile.TemporaryDirectory(prefix="fdai-provider-schema-readback-") as temporary:
            evidence = asyncio.run(
                collect_provider_schema_deployment_evidence(
                    store=store,
                    audit_reader=store,
                    ledger_root=Path(temporary),
                    application_source_commit=args.application_source_commit,
                    runtime_image_revision=args.runtime_image_revision,
                    plan_id=args.plan_id,
                    execution_name=args.execution_name,
                    execution_status=args.execution_status,
                    started_at=started_at,
                )
            )
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.output.chmod(0o600)
    except (OSError, ValueError, ProviderSchemaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - provider details must not cross this boundary
        print(
            f"error: provider schema deployment evidence unavailable ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())


__all__ = [
    "ProviderSchemaAuditReader",
    "collect_provider_schema_deployment_evidence",
    "main",
]
