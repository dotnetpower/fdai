"""Command-line entry points for bounded commerce assessment and browser evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig
from fdai_service_contracts import AksCommerceMetric, AksCommerceSlo, AksCommerceWorkload

from fdai_aks_commerce.assessment import assess_aks_commerce
from fdai_aks_commerce.coordinator import PROJECTION_KEY_PREFIX
from fdai_aks_commerce.models import AksCommerceEvidenceFrame
from fdai_aks_commerce.synthetic import (
    AsyncPlaywrightStorefrontDriver,
    StorefrontJourneyConfig,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one bounded command and return a process status."""

    parser = argparse.ArgumentParser(prog="fdai-aks-commerce-assess")
    subcommands = parser.add_subparsers(dest="command", required=True)
    assess = subcommands.add_parser("assess")
    assess.add_argument("--input", type=Path, required=True)
    assess.add_argument("--persist", action="store_true")
    journey = subcommands.add_parser("journey")
    journey.add_argument("--url", required=True)
    journey.add_argument("--authorization-ref", required=True)
    journey.add_argument("--authorization-expires-at", required=True)
    args = parser.parse_args(argv)
    if args.command == "assess":
        return asyncio.run(_assess(args.input, persist=args.persist))
    return asyncio.run(
        _journey(
            args.url,
            args.authorization_ref,
            _parse_datetime(args.authorization_expires_at, "authorization-expires-at"),
        )
    )


async def _assess(path: Path, *, persist: bool) -> int:
    frame = _load_frame(path)
    projection = assess_aks_commerce(frame)
    if persist:
        dsn = os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
        if not dsn:
            raise RuntimeError("FDAI_STATE_STORE_DSN is required when --persist is selected")
        store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
        payload = projection.model_dump(mode="json")
        prefix = f"{PROJECTION_KEY_PREFIX}{projection.service_id}:"
        await store.write_state(f"{prefix}{projection.assessment_id}", payload)
        await store.write_state(f"{prefix}latest", payload)
    print(projection.model_dump_json())
    return 0


async def _journey(
    url: str,
    authorization_ref: str,
    authorization_expires_at: datetime,
) -> int:
    result = await AsyncPlaywrightStorefrontDriver().run(
        StorefrontJourneyConfig(
            url=url,
            authorization_ref=authorization_ref,
            authorization_expires_at=authorization_expires_at,
        )
    )
    print(
        json.dumps(
            {
                "observed_at": result.observed_at.isoformat(),
                "success": result.success,
                "failed_step": result.failed_step,
                "duration_ms": result.duration_ms,
                "evidence_ref": result.evidence_ref,
                "authorization_ref": result.authorization_ref,
                "synthetic": result.synthetic,
                "execution_authority": result.execution_authority,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result.success else 2


def _load_frame(path: Path) -> AksCommerceEvidenceFrame:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("AKS commerce input must be a readable UTF-8 JSON document") from exc
    if not isinstance(value, Mapping):
        raise ValueError("AKS commerce input must contain a JSON object")
    required = {
        "service_id",
        "observed_at",
        "window_start",
        "window_end",
        "dependency_path",
        "workloads",
        "slos",
        "metrics",
        "evidence_refs",
    }
    optional = {
        "evidence_gaps",
        "deployment_changed",
        "rollout_stalled",
        "order_store_pressure",
        "prior_degraded",
        "synthetic",
    }
    if not required <= set(value) or not set(value) <= required | optional:
        raise ValueError("AKS commerce input fields are incomplete or unknown")
    return AksCommerceEvidenceFrame(
        service_id=_service_id(value),
        observed_at=_datetime(value, "observed_at"),
        window_start=_datetime(value, "window_start"),
        window_end=_datetime(value, "window_end"),
        dependency_path=_text_tuple(value, "dependency_path"),
        workloads=tuple(
            AksCommerceWorkload.model_validate(item) for item in _objects(value, "workloads")
        ),
        slos=tuple(AksCommerceSlo.model_validate(item) for item in _objects(value, "slos")),
        metrics=tuple(
            AksCommerceMetric.model_validate(item) for item in _objects(value, "metrics")
        ),
        evidence_refs=_text_tuple(value, "evidence_refs"),
        evidence_gaps=_text_tuple(value, "evidence_gaps", required=False),
        deployment_changed=_boolean(value, "deployment_changed"),
        rollout_stalled=_boolean(value, "rollout_stalled"),
        order_store_pressure=_boolean(value, "order_store_pressure"),
        prior_degraded=_boolean(value, "prior_degraded"),
        synthetic=_boolean(value, "synthetic"),
    )


def _text(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"AKS commerce {key} must be non-empty text")
    return item


def _service_id(
    value: Mapping[str, Any],
) -> Literal["catalog-browse", "order-fulfillment"]:
    item = _text(value, "service_id")
    if item == "catalog-browse":
        return "catalog-browse"
    if item == "order-fulfillment":
        return "order-fulfillment"
    raise ValueError("AKS commerce service_id is unsupported")


def _datetime(value: Mapping[str, Any], key: str) -> datetime:
    try:
        item = datetime.fromisoformat(_text(value, key).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"AKS commerce {key} must be an ISO 8601 timestamp") from exc
    if item.tzinfo is None or item.utcoffset() is None:
        raise ValueError(f"AKS commerce {key} must include a timezone")
    return item


def _parse_datetime(value: str, label: str) -> datetime:
    try:
        item = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO 8601 timestamp") from exc
    if item.tzinfo is None or item.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return item


def _text_tuple(
    value: Mapping[str, Any],
    key: str,
    *,
    required: bool = True,
) -> tuple[str, ...]:
    item = value.get(key)
    if item is None and not required:
        return ()
    if not isinstance(item, list) or any(not isinstance(child, str) for child in item):
        raise ValueError(f"AKS commerce {key} must be an array of strings")
    return tuple(item)


def _objects(value: Mapping[str, Any], key: str) -> tuple[Mapping[str, Any], ...]:
    item = value.get(key)
    if not isinstance(item, list) or any(not isinstance(child, Mapping) for child in item):
        raise ValueError(f"AKS commerce {key} must be an array of objects")
    return tuple(item)


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key, False)
    if not isinstance(item, bool):
        raise ValueError(f"AKS commerce {key} must be a boolean")
    return item


if __name__ == "__main__":
    raise SystemExit(main())
