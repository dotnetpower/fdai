#!/usr/bin/env python3
"""Sanitize bounded model deprecation notices from an Azure provider catalog."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TypeGuard

_MAX_PROVIDER_MODELS = 4_096
_MAX_MODEL_SKUS = 128


def extract_provider_deprecations(
    provider_models: Sequence[Mapping[str, object]],
    *,
    as_of: date,
    horizon_days: int = 60,
) -> list[dict[str, str]]:
    """Return version-scoped provider deprecations within the review horizon."""
    if isinstance(horizon_days, bool) or not 1 <= horizon_days <= 366:
        raise ValueError("deprecation horizon must be between 1 and 366 days")
    if len(provider_models) > _MAX_PROVIDER_MODELS:
        raise ValueError("provider model catalog exceeds the entry limit")
    horizon = as_of + timedelta(days=horizon_days)
    notices: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for raw in provider_models:
        if not isinstance(raw, Mapping):
            raise ValueError("provider model entry must be an object")
        nested = raw.get("model")
        model = nested if _is_string_mapping(nested) else raw
        model_retirement = _retirement_value(raw, model)
        raw_skus = raw.get("skus")
        if raw_skus is None:
            raw_skus = model.get("skus")
        if raw_skus is not None and not isinstance(raw_skus, list):
            raise ValueError("provider model skus must be an array")
        if isinstance(raw_skus, list) and len(raw_skus) > _MAX_MODEL_SKUS:
            raise ValueError("provider model skus exceed the entry limit")
        sku_entries = raw_skus if isinstance(raw_skus, list) else []
        if sku_entries:
            for raw_sku in sku_entries:
                if not _is_string_mapping(raw_sku):
                    raise ValueError("provider model sku must be an object")
                sku_retirement = raw_sku.get("deprecationDate")
                if (
                    sku_retirement is None
                    and model_retirement is None
                    and (model.get("lifecycleStatus") == "Deprecating")
                ):
                    raise ValueError("deprecating provider model sku is missing a date")
                _add_notice(
                    notices,
                    model=model,
                    retirement=_earliest_retirement(sku_retirement, model_retirement),
                    sku=raw_sku.get("name"),
                    horizon=horizon,
                )
        else:
            _add_notice(
                notices,
                model=model,
                retirement=_earliest_retirement(model_retirement),
                sku=None,
                horizon=horizon,
            )
        if (
            model.get("lifecycleStatus") == "Deprecating"
            and model_retirement is None
            and not sku_entries
        ):
            raise ValueError("deprecating provider model is missing an inference date")
    return [notices[key] for key in sorted(notices)]


def _add_notice(
    notices: dict[tuple[str, str, str, str], dict[str, str]],
    *,
    model: Mapping[str, object],
    retirement: date | None,
    sku: object | None,
    horizon: date,
) -> None:
    if retirement is None:
        return
    if retirement > horizon:
        return
    family = _required_string(model.get("name") or model.get("family"), "model family")
    version = _required_string(model.get("version"), "model version")
    sku_name = _optional_string(sku, "model sku")
    retirement_text = retirement.isoformat()
    notice = {
        "family": family,
        "version": version,
        "retirement_date": retirement_text,
    }
    if sku_name is not None:
        notice["sku"] = sku_name
    notices[(family, version, sku_name or "", retirement_text)] = notice


def _earliest_retirement(*values: object | None) -> date | None:
    dates = [_calendar_date(value) for value in values if value is not None]
    return min(dates) if dates else None


def _retirement_value(
    raw: Mapping[str, object],
    model: Mapping[str, object],
) -> object | None:
    for source in (raw, model):
        deprecation = source.get("deprecation")
        if _is_string_mapping(deprecation):
            inference = deprecation.get("inference")
            if inference is not None:
                return inference
        for key in ("retirementDate", "deprecationDate"):
            fallback = source.get(key)
            if fallback is not None:
                return fallback
    return None


def _is_string_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


def _calendar_date(value: object) -> date:
    text = _required_string(value, "retirement date")
    try:
        return date.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError as exc:
            raise ValueError("retirement date must be ISO 8601") from exc


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be a bounded non-empty string")
    return value.strip()


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, name)


def _load_provider_models(path: Path) -> list[Mapping[str, object]]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError(f"{path} must contain a JSON array")
    models: list[Mapping[str, object]] = []
    for item in loaded:
        if not isinstance(item, Mapping):
            raise ValueError(f"{path} must contain only JSON objects")
        models.append(item)
    return models


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-models", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--horizon-days", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        notices = extract_provider_deprecations(
            _load_provider_models(args.provider_models),
            as_of=args.as_of,
            horizon_days=args.horizon_days,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"model-lifecycle-provider: {type(exc).__name__}", file=sys.stderr)
        return 2
    args.out.write_text(
        json.dumps(notices, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["extract_provider_deprecations", "main"]
