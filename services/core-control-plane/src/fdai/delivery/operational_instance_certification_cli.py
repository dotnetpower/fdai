"""Capture and reduce local OI-12 PostgreSQL certification evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from fdai.core.ontology_platform.operational_instance_certification import (
    OperationalInstanceCertificationReceipt,
)
from fdai.delivery.operational_instance_certification import (
    OperationalCertificationSnapshot,
    build_operational_certification_snapshot,
    reduce_operational_instance_certification,
)
from fdai.delivery.operational_instance_certification_archive import (
    LocalArchiveExerciseReceipt,
    run_local_archive_exercise,
)
from fdai.delivery.operational_instance_certification_postgres import (
    PostgresOperationalCertificationSource,
    PostgresOperationalCertificationSourceConfig,
)
from fdai.delivery.persistence.postgres_operational_archive import (
    PostgresOperationalArchiveStore,
    PostgresOperationalArchiveStoreConfig,
)


def snapshot_record(snapshot: OperationalCertificationSnapshot) -> dict[str, object]:
    """Serialize one sanitized aggregate snapshot without a database coordinate."""

    return {
        "schema_version": "1.0.0",
        "measured_at": snapshot.measured_at.astimezone(UTC).isoformat(),
        "ontology_release_digest": snapshot.ontology_release_digest,
        "database_bytes": snapshot.database_bytes,
        "freshness_seconds": _decimal(snapshot.freshness_seconds),
        "api_pressure_ratio": _decimal(snapshot.api_pressure_ratio),
        "lag_seconds": _decimal(snapshot.lag_seconds),
        "rollup_total_count": snapshot.rollup_total_count,
        "rollup_complete_count": snapshot.rollup_complete_count,
        "restore_total_count": snapshot.restore_total_count,
        "restore_passed_count": snapshot.restore_passed_count,
        "provider_failure_recovery_seconds": _decimal(snapshot.provider_failure_recovery_seconds),
        "digest": snapshot.digest,
    }


def snapshot_from_record(record: Mapping[str, object]) -> OperationalCertificationSnapshot:
    """Decode a snapshot and reject stale or tampered content before reduction."""

    if record.get("schema_version") != "1.0.0":
        raise ValueError("unsupported operational certification snapshot schema")
    snapshot = build_operational_certification_snapshot(
        measured_at=_timestamp(record.get("measured_at")),
        ontology_release_digest=_required_str(
            record.get("ontology_release_digest"), "ontology release"
        ),
        database_bytes=_optional_int(record.get("database_bytes")),
        freshness_seconds=_optional_decimal(record.get("freshness_seconds")),
        api_pressure_ratio=_optional_decimal(record.get("api_pressure_ratio")),
        lag_seconds=_optional_decimal(record.get("lag_seconds")),
        rollup_total_count=_required_int(record.get("rollup_total_count"), "rollup total"),
        rollup_complete_count=_required_int(record.get("rollup_complete_count"), "rollup complete"),
        restore_total_count=_required_int(record.get("restore_total_count"), "restore total"),
        restore_passed_count=_required_int(record.get("restore_passed_count"), "restore passed"),
        provider_failure_recovery_seconds=_optional_decimal(
            record.get("provider_failure_recovery_seconds")
        ),
    )
    if record.get("digest") != snapshot.digest:
        raise ValueError("operational certification snapshot digest mismatch")
    return snapshot


def receipt_record(receipt: OperationalInstanceCertificationReceipt) -> dict[str, object]:
    """Serialize a no-authority receipt with decimal values preserved as strings."""

    return {
        "schema_version": receipt.schema_version,
        "window_start": receipt.window_start.astimezone(UTC).isoformat(),
        "window_end": receipt.window_end.astimezone(UTC).isoformat(),
        "recorded_at": receipt.recorded_at.astimezone(UTC).isoformat(),
        "ontology_release_digest": receipt.ontology_release_digest,
        "measurements": [
            {
                "axis": measurement.axis.value,
                "status": measurement.status.value,
                "measured_at": measurement.measured_at.astimezone(UTC).isoformat(),
                "value": _decimal(measurement.value),
                "unit": measurement.unit,
                "reason_codes": list(measurement.reason_codes),
                "evidence_digests": list(measurement.evidence_digests),
            }
            for measurement in receipt.measurements
        ],
        "complete": receipt.complete,
        "unavailable_axes": [axis.value for axis in receipt.unavailable_axes],
        "observation_authority": receipt.observation_authority,
        "mutation_authority": receipt.mutation_authority,
        "execution_authority": receipt.execution_authority,
        "digest": receipt.digest,
    }


def archive_exercise_record(receipt: LocalArchiveExerciseReceipt) -> dict[str, object]:
    """Serialize the local archive exercise without adding purge authority."""

    return {
        "schema_version": "1.0.0",
        "rollup_digest": receipt.rollup_digest,
        "manifest_digest": receipt.manifest_digest,
        "verification_digest": receipt.verification_digest,
        "restore_digest": receipt.restore_digest,
        "artifact_digest": receipt.artifact_digest,
        "passed": receipt.passed,
        "observation_authority": receipt.observation_authority,
        "mutation_authority": receipt.mutation_authority,
        "execution_authority": receipt.execution_authority,
        "digest": receipt.digest,
    }


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    dsn = os.environ.get("FDAI_DATABASE_URL", "").strip()
    if not dsn:
        raise ValueError("FDAI_DATABASE_URL MUST be configured")
    source = PostgresOperationalCertificationSource(
        config=PostgresOperationalCertificationSourceConfig(dsn=dsn)
    )
    end = await source.capture()
    if arguments.command == "capture":
        _write_record(arguments.output, snapshot_record(end))
        return {"snapshot_digest": end.digest, "output": str(arguments.output)}
    start = snapshot_from_record(_read_record(arguments.start))
    exercise: LocalArchiveExerciseReceipt | None = None
    if arguments.command == "archive-certify":
        exercise = await run_local_archive_exercise(
            start,
            end,
            artifact_path=arguments.archive_artifact,
            store=PostgresOperationalArchiveStore(
                config=PostgresOperationalArchiveStoreConfig(dsn=dsn)
            ),
        )
        if not exercise.passed:
            raise RuntimeError("operational archive exercise did not pass")
        _write_record(arguments.exercise_output, archive_exercise_record(exercise))
        end = await source.capture()
    receipt = reduce_operational_instance_certification(
        start,
        end,
        recorded_at=end.measured_at,
    )
    _write_record(arguments.output, receipt_record(receipt))
    if arguments.end_output is not None:
        _write_record(arguments.end_output, snapshot_record(end))
    summary: dict[str, object] = {
        "receipt_digest": receipt.digest,
        "complete": receipt.complete,
        "unavailable_axes": [axis.value for axis in receipt.unavailable_axes],
        "output": str(arguments.output),
    }
    if exercise is not None:
        summary["archive_exercise_digest"] = exercise.digest
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="operational-instance-certification")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--output", required=True, type=Path)
    certify = commands.add_parser("certify")
    certify.add_argument("--start", required=True, type=Path)
    certify.add_argument("--output", required=True, type=Path)
    certify.add_argument("--end-output", type=Path)
    archive_certify = commands.add_parser("archive-certify")
    archive_certify.add_argument("--start", required=True, type=Path)
    archive_certify.add_argument("--output", required=True, type=Path)
    archive_certify.add_argument("--end-output", required=True, type=Path)
    archive_certify.add_argument("--archive-artifact", required=True, type=Path)
    archive_certify.add_argument("--exercise-output", required=True, type=Path)
    return parser


def _read_record(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("operational certification artifact MUST be valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ValueError("operational certification artifact MUST be an object")
    return value


def _write_record(path: Path, record: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("operational certification timestamp is unavailable")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("operational certification timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("operational certification timestamp MUST be timezone-aware")
    return parsed


def _required_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"operational certification {name} is unavailable")
    return value


def _optional_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (ArithmeticError, ValueError) as exc:
        raise ValueError("operational certification decimal is invalid") from exc
    if not parsed.is_finite():
        raise ValueError("operational certification decimal MUST be finite")
    return parsed


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _required_int(value, "integer")


def _required_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"operational certification {name} count is invalid")
    return value


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


def main(argv: Sequence[str] | None = None) -> int:
    """Run one capture or certification step without waiting or retrying providers."""

    try:
        summary = asyncio.run(_run(_parser().parse_args(argv)))
    except psycopg.Error as exc:
        print(
            json.dumps(
                {"status": "failed", "reason": f"database_{type(exc).__name__}"},
                sort_keys=True,
            )
        )
        return 3
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "completed", **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "archive_exercise_record",
    "main",
    "receipt_record",
    "snapshot_from_record",
    "snapshot_record",
]
