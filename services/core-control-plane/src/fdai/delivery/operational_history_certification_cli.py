"""Persist a pinned-revision OI-16 operational history certification receipt."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryCertificationReceipt,
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
) -> OperationalHistoryCertificationReceipt:
    """Validate exact scenario evidence and build a no-authority receipt."""

    if manifest.get("schema_version") != "1.0.0":
        raise ValueError("operational history certification manifest schema is unsupported")
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
    return build_operational_history_certification(
        results,
        source_revision=source_revision,
        ontology_release_digest=ontology_release_digest,
        window_start=window_start,
        window_end=window_end,
        recorded_at=recorded_at,
        deployment_receipt_digest=deployment_receipt_digest,
    )


async def run(
    *,
    evidence_path: Path,
    output_path: Path,
    source_revision: str,
    ontology_release_digest: str,
    dsn: str,
    deployment_receipt_digest: str | None = None,
) -> dict[str, object]:
    """Build, persist, and privately write one certification receipt."""

    manifest = _read_manifest(evidence_path)
    receipt = build_certification_from_manifest(
        manifest,
        source_revision=source_revision,
        ontology_release_digest=ontology_release_digest,
        deployment_receipt_digest=deployment_receipt_digest,
    )
    store = PostgresOperationalHistoryStore(
        config=PostgresOperationalHistoryConfig(
            dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        )
    )
    await store.append_certification(receipt)
    _write_private(output_path, certification_record(receipt))
    return {
        "receipt_digest": receipt.digest,
        "deterministic_complete": receipt.deterministic_complete,
        "operationally_validated": receipt.operationally_validated,
        "output": str(output_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="operational-history-certification")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--ontology-release-digest", required=True)
    parser.add_argument("--deployment-receipt-digest")
    args = parser.parse_args(argv)
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        parser.error("FDAI_DATABASE_URL is required")
    summary = asyncio.run(
        run(
            evidence_path=args.evidence,
            output_path=args.output,
            source_revision=args.source_revision,
            ontology_release_digest=args.ontology_release_digest,
            dsn=dsn,
            deployment_receipt_digest=args.deployment_receipt_digest,
        )
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["deterministic_complete"] else 1


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


if __name__ == "__main__":
    raise SystemExit(main())
