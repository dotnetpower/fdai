"""Append-only filesystem ledger for complete provider schema evidence."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from fdai.delivery.provider_schema import (
    ProviderSchemaCoverage,
    ProviderSchemaError,
    ProviderSchemaSnapshot,
    provider_schema_observation_time,
    provider_schema_snapshot_from_mapping,
)


class ProviderSchemaLedger:
    """Persist immutable snapshots, run receipts, and accepted baseline pointers."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def read_baseline(self, provider: str) -> ProviderSchemaSnapshot | None:
        pointer = self._read_json(
            self._provider_root(provider) / "baseline.json",
            optional=True,
        )
        if pointer is None:
            return None
        digest = pointer.get("schema_digest")
        if not isinstance(digest, str):
            raise ProviderSchemaError("provider schema baseline pointer is invalid")
        return self._read_snapshot(provider, digest)

    def read_baseline_observed_at(self, provider: str) -> datetime | None:
        pointer = self._read_json(self._provider_root(provider) / "baseline.json", optional=True)
        if pointer is None:
            return None
        raw = pointer.get("observed_at")
        if not isinstance(raw, str):
            raise ProviderSchemaError("provider schema baseline observation time is invalid")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ProviderSchemaError(
                "provider schema baseline observation time is invalid"
            ) from exc
        if parsed.tzinfo is None:
            raise ProviderSchemaError("provider schema baseline observation time MUST be aware")
        return parsed

    def record_snapshot(
        self,
        snapshot: ProviderSchemaSnapshot,
        *,
        observed_at: datetime,
        accept_baseline: bool,
    ) -> None:
        provider_root = self._provider_root(snapshot.provider)
        snapshots = provider_root / "snapshots"
        snapshots.mkdir(parents=True, exist_ok=True)
        digest_hex = snapshot.schema_digest.removeprefix("sha256:")
        snapshot_path = snapshots / f"{digest_hex}.json"
        payload = snapshot.to_mapping()
        if snapshot_path.exists():
            existing = provider_schema_snapshot_from_mapping(
                self._read_required_json(snapshot_path)
            )
            if existing != snapshot:
                raise ProviderSchemaError("provider schema digest collision")
        else:
            self._atomic_write(snapshot_path, payload)
        observed_pointer = {
            "schema_version": "1.0.0",
            "provider": snapshot.provider,
            "schema_digest": snapshot.schema_digest,
            "observed_at": provider_schema_observation_time(observed_at),
            "grants_authority": False,
        }
        self._atomic_write(provider_root / "observed.json", observed_pointer)
        if accept_baseline:
            self._atomic_write(provider_root / "baseline.json", observed_pointer)

    def record_run(
        self,
        provider: str,
        receipt: Mapping[str, object],
        *,
        update_last: bool = True,
    ) -> str:
        provider_root = self._provider_root(provider)
        runs = provider_root / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            dict(receipt), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        path = runs / f"{digest}.json"
        if path.exists():
            if path.read_bytes() != payload + b"\n":
                raise ProviderSchemaError("provider schema run receipt digest collision")
        else:
            self._atomic_write_bytes(path, payload + b"\n")
        if update_last:
            self._atomic_write(
                provider_root / "last-run.json",
                {
                    "schema_version": "1.0.0",
                    "provider": provider.casefold(),
                    "receipt_digest": f"sha256:{digest}",
                },
            )
        return f"sha256:{digest}"

    def record_coverage(self, provider: str, coverage: ProviderSchemaCoverage) -> str:
        provider_root = self._provider_root(provider)
        coverage_root = provider_root / "coverage"
        coverage_root.mkdir(parents=True, exist_ok=True)
        mapping = coverage.to_mapping()
        payload = json.dumps(
            mapping, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        self._atomic_write_bytes(
            coverage_root / f"{digest}.json",
            payload + b"\n",
            immutable=True,
        )
        self._atomic_write(
            provider_root / "coverage.json",
            {
                "schema_version": "1.0.0",
                "provider": provider.casefold(),
                "schema_digest": coverage.schema_digest,
                "coverage_digest": f"sha256:{digest}",
                "type_count": len(coverage.entries),
                "modeled_count": coverage.modeled_count,
                "grants_authority": False,
            },
        )
        return f"sha256:{digest}"

    def read_last_run(self, provider: str) -> dict[str, object] | None:
        pointer = self._read_json(self._provider_root(provider) / "last-run.json", optional=True)
        if pointer is None:
            return None
        digest = pointer.get("receipt_digest")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ProviderSchemaError("provider schema run pointer is invalid")
        return self._read_required_json(
            self._provider_root(provider) / "runs" / f"{digest.removeprefix('sha256:')}.json"
        )

    def record_review_package(self, provider: str, package: Mapping[str, object]) -> str:
        review_root = self._provider_root(provider) / "review-packages"
        review_root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            dict(package), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        self._atomic_write_bytes(review_root / f"{digest}.json", payload + b"\n", immutable=True)
        return f"sha256:{digest}"

    def _read_snapshot(self, provider: str, digest: str) -> ProviderSchemaSnapshot:
        if not digest.startswith("sha256:"):
            raise ProviderSchemaError("provider schema pointer digest is invalid")
        stem = self._provider_root(provider) / "snapshots" / digest.removeprefix("sha256:")
        json_path = stem.with_suffix(".json")
        if json_path.exists():
            raw = self._read_required_json(json_path)
        else:
            compressed_path = stem.with_suffix(".json.gz")
            try:
                raw_value = json.loads(gzip.decompress(compressed_path.read_bytes()))
            except (OSError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
                raise ProviderSchemaError("provider schema compressed snapshot is invalid") from exc
            if not isinstance(raw_value, dict):
                raise ProviderSchemaError("provider schema compressed snapshot MUST be an object")
            raw = raw_value
        return provider_schema_snapshot_from_mapping(raw)

    def _provider_root(self, provider: str) -> Path:
        normalized = provider.strip().casefold()
        if not normalized or not normalized.replace("-", "").isalnum():
            raise ProviderSchemaError("provider schema ledger provider is invalid")
        return self._root / normalized

    @staticmethod
    def _read_json(path: Path, *, optional: bool) -> dict[str, object] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if optional:
                return None
            raise ProviderSchemaError(
                f"provider schema ledger file is missing: {path.name}"
            ) from None
        except (OSError, json.JSONDecodeError) as exc:
            raise ProviderSchemaError(
                f"provider schema ledger file is invalid: {path.name}"
            ) from exc
        if not isinstance(raw, dict):
            raise ProviderSchemaError(f"provider schema ledger file MUST be an object: {path.name}")
        return raw

    @classmethod
    def _read_required_json(cls, path: Path) -> dict[str, object]:
        raw = cls._read_json(path, optional=False)
        if raw is None:  # pragma: no cover - optional=False raises for absence
            raise ProviderSchemaError(f"provider schema ledger file is missing: {path.name}")
        return raw

    @staticmethod
    def _atomic_write(path: Path, value: Mapping[str, object]) -> None:
        payload = (
            json.dumps(dict(value), ensure_ascii=True, indent=2, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        ProviderSchemaLedger._atomic_write_bytes(path, payload)

    @staticmethod
    def _atomic_write_bytes(path: Path, payload: bytes, *, immutable: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if immutable and path.exists():
            if path.read_bytes() != payload:
                raise ProviderSchemaError("provider schema immutable ledger conflict")
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["ProviderSchemaLedger"]
