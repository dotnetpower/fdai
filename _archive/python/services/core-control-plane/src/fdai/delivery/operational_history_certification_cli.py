"""Persist a pinned-revision OI-16 operational history certification receipt."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryCertificationReceipt,
    OperationalHistoryProtectedBinding,
    OperationalHistoryScenario,
    OperationalHistoryScenarioResult,
    OperationalHistoryScenarioStatus,
    build_operational_history_certification,
    certification_record,
)
from fdai.delivery.persistence.postgres_operational_history import (
    PostgresOperationalHistoryConfig,
    PostgresOperationalHistoryStore,
)

_MAX_EVIDENCE_FILE_BYTES = 1024 * 1024


def build_certification_from_manifest(
    manifest: Mapping[str, object],
    *,
    source_revision: str,
    ontology_release_digest: str,
    deployment_receipt_digest: str | None = None,
    protected_binding: OperationalHistoryProtectedBinding | None = None,
) -> OperationalHistoryCertificationReceipt:
    """Validate exact scenario evidence and build a no-authority receipt."""

    if manifest.get("schema_version") != "1.0.0":
        raise ValueError("operational history certification manifest schema is unsupported")
    source_revision_digest = "sha256:" + hashlib.sha256(source_revision.encode()).hexdigest()
    if manifest.get("source_revision_digest") != source_revision_digest:
        raise ValueError(
            "operational history certification source revision does not match manifest"
        )
    if manifest.get("ontology_release_digest") != ontology_release_digest:
        raise ValueError(
            "operational history certification ontology release does not match manifest"
        )
    if protected_binding is not None:
        if manifest.get("campaign_id") != protected_binding.campaign_request_id:
            raise ValueError("protected campaign request does not match certification manifest")
        if manifest.get("phase") != "merged":
            raise ValueError("protected certification requires merged restart-phase evidence")
    window_start = _timestamp(manifest.get("window_start"), "window_start")
    window_end = _timestamp(manifest.get("window_end"), "window_end")
    recorded_at = _timestamp(manifest.get("recorded_at"), "recorded_at")
    raw_scenarios = manifest.get("scenarios")
    if not isinstance(raw_scenarios, Mapping):
        raise ValueError("operational history certification scenarios MUST be an object")
    extra = set(raw_scenarios) - {item.value for item in OperationalHistoryScenario}
    if extra:
        raise ValueError("operational history certification contains unknown scenarios")
    results: list[OperationalHistoryScenarioResult] = []
    for scenario in OperationalHistoryScenario:
        raw = raw_scenarios.get(scenario.value)
        if raw is None:
            results.append(
                OperationalHistoryScenarioResult(
                    scenario=scenario,
                    status=OperationalHistoryScenarioStatus.UNAVAILABLE,
                    evidence_digests=(),
                    reason_codes=("scenario_evidence_unavailable",),
                )
            )
            continue
        if not isinstance(raw, Mapping):
            raise ValueError("operational history scenario evidence MUST be an object")
        status_value = raw.get("status")
        if not isinstance(status_value, str):
            raise ValueError("operational history scenario status MUST be a string")
        status = OperationalHistoryScenarioStatus(status_value)
        evidence = _string_tuple(raw.get("evidence_digests"), "evidence_digests")
        reasons = _string_tuple(raw.get("reason_codes", []), "reason_codes")
        results.append(
            OperationalHistoryScenarioResult(
                scenario=scenario,
                status=status,
                evidence_digests=evidence,
                reason_codes=reasons,
            )
        )
    receipt = build_operational_history_certification(
        results,
        source_revision=source_revision,
        ontology_release_digest=ontology_release_digest,
        window_start=window_start,
        window_end=window_end,
        recorded_at=recorded_at,
        deployment_receipt_digest=deployment_receipt_digest,
        protected_binding=protected_binding,
    )
    if manifest.get("deterministic_complete") is not receipt.deterministic_complete:
        raise ValueError("operational history certification completeness conflicts with manifest")
    return receipt


async def run(
    *,
    evidence_path: Path,
    output_path: Path,
    source_revision: str,
    ontology_release_digest: str,
    dsn: str,
    deployment_receipt_digest: str | None = None,
    protected_binding: OperationalHistoryProtectedBinding | None = None,
) -> dict[str, object]:
    """Build, persist, and privately write one certification receipt."""

    manifest = _read_manifest(evidence_path)
    receipt = build_certification_from_manifest(
        manifest,
        source_revision=source_revision,
        ontology_release_digest=ontology_release_digest,
        deployment_receipt_digest=deployment_receipt_digest,
        protected_binding=protected_binding,
    )
    persisted = False
    if receipt.operationally_validated:
        store = PostgresOperationalHistoryStore(
            config=PostgresOperationalHistoryConfig(
                dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
            )
        )
        persisted = await store.append_certification(receipt)
        if not persisted:
            persisted = True
        _write_private(output_path, certification_record(receipt))
    return {
        "receipt_digest": receipt.digest,
        "deterministic_complete": receipt.deterministic_complete,
        "operationally_validated": receipt.operationally_validated,
        "persisted": persisted,
        "output": str(output_path) if receipt.operationally_validated else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="operational-history-certification")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--ontology-release-digest", required=True)
    parser.add_argument("--deployment-receipt-digest")
    parser.add_argument("--required-ci-run-id", type=int)
    parser.add_argument("--runtime-image-revision")
    parser.add_argument("--runtime-image-digest")
    parser.add_argument("--runtime-attestation-digest")
    parser.add_argument("--deployment-revision")
    parser.add_argument("--deployment-apply-run-id", type=int)
    parser.add_argument("--campaign-run-id", type=int)
    parser.add_argument("--campaign-request-id")
    args = parser.parse_args(argv)
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("FDAI_DATABASE_URL is required")
    protected_binding = _protected_binding(args)
    summary = asyncio.run(
        run(
            evidence_path=args.evidence,
            output_path=args.output,
            source_revision=args.source_revision,
            ontology_release_digest=args.ontology_release_digest,
            dsn=dsn,
            deployment_receipt_digest=args.deployment_receipt_digest,
            protected_binding=protected_binding,
        )
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["operationally_validated"] else 1


def _read_manifest(path: Path) -> Mapping[str, object]:
    if not path.is_file() or path.stat().st_size > _MAX_EVIDENCE_FILE_BYTES:
        raise ValueError("operational history certification evidence file is unavailable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("operational history certification evidence is invalid") from exc
    if not isinstance(value, Mapping):
        raise ValueError("operational history certification evidence MUST be an object")
    return value


def _write_private(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        + b"\n"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"operational history certification {name} MUST be RFC 3339 text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"operational history certification {name} MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"operational history certification {name} MUST be a string array")
    return tuple(sorted(set(value)))


def _protected_binding(args: argparse.Namespace) -> OperationalHistoryProtectedBinding | None:
    values = (
        args.deployment_receipt_digest,
        args.required_ci_run_id,
        args.runtime_image_revision,
        args.runtime_image_digest,
        args.runtime_attestation_digest,
        args.deployment_revision,
        args.deployment_apply_run_id,
        args.campaign_run_id,
        args.campaign_request_id,
    )
    if not any(value is not None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("protected certification binding arguments MUST be supplied together")
    return OperationalHistoryProtectedBinding(
        source_revision=args.source_revision,
        required_ci_run_id=args.required_ci_run_id,
        runtime_image_revision=args.runtime_image_revision,
        runtime_image_digest=args.runtime_image_digest,
        runtime_attestation_digest=args.runtime_attestation_digest,
        deployment_revision=args.deployment_revision,
        deployment_apply_run_id=args.deployment_apply_run_id,
        deployment_receipt_digest=args.deployment_receipt_digest,
        campaign_run_id=args.campaign_run_id,
        campaign_request_id=args.campaign_request_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
