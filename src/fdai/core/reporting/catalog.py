"""Reporting catalog loader - YAML -> ReportSpec.

Reads every ``*.yaml`` under a root directory (typically
``rule-catalog/reports/``), validates each file against
:file:`rule-catalog/reports/schema/report.schema.json`, and aggregates
schema violations into one :class:`ReportCatalogError`.

Fail-closed:

- unknown top-level keys, malformed ``time_range``, or a widget type
  the (optionally-supplied) allowlist does not know is a fatal error;
- duplicate report ids across files is fatal;
- YAML with two documents in one file is fatal.

The loader never touches state, never runs the engine, never opens a
network. It returns plain :class:`~fdai.core.reporting.models.ReportSpec`
values that a composition root passes to
:class:`~fdai.core.reporting.registry.ReportCatalog`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.core.reporting.models import (
    QuerySpec,
    ReportSpec,
    TimeRange,
    Variable,
    WidgetSpec,
)

_DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[4]
    / "rule-catalog"
    / "reports"
    / "schema"
    / "report.schema.json"
)
_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
_DURATION_UNITS: dict[str, str] = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}


@dataclass(frozen=True, slots=True)
class ReportCatalogIssue:
    """One validation error attributable to a file / mapping."""

    origin: str
    message: str


class ReportCatalogError(ValueError):
    """Aggregated validation failure for the reporting catalog."""

    def __init__(self, issues: Sequence[ReportCatalogIssue]) -> None:
        self.issues = tuple(issues)
        preview = "; ".join(f"{i.origin}: {i.message}" for i in issues[:5])
        suffix = f" (+{len(issues) - 5} more)" if len(issues) > 5 else ""
        super().__init__(f"report catalog validation failed: {preview}{suffix}")


def default_report_schema_path() -> Path:
    """Return the shipped JSON Schema path."""
    return _DEFAULT_SCHEMA_PATH


def load_report_from_mapping(
    raw: Mapping[str, Any],
    *,
    schema_path: Path | None = None,
    allowed_widget_types: frozenset[str] | None = None,
    allowed_datasources: frozenset[str] | None = None,
    origin: str = "<mapping>",
) -> ReportSpec:
    """Validate + convert one mapping into a :class:`ReportSpec`.

    Aggregates schema and cross-cutting issues into a single
    :class:`ReportCatalogError`.
    """
    issues: list[ReportCatalogIssue] = []
    validator = _validator(schema_path)
    for schema_error in sorted(
        validator.iter_errors(dict(raw)),
        key=lambda e: list(e.absolute_path),
    ):
        pointer = "/".join(str(p) for p in schema_error.absolute_path) or "<root>"
        issues.append(ReportCatalogIssue(origin, f"{pointer}: {schema_error.message}"))
    if issues:
        raise ReportCatalogError(issues)

    try:
        time_range = _time_range(raw["time_range"])
    except ValueError as exc:
        issues.append(ReportCatalogIssue(origin, f"time_range: {exc}"))

    variables = tuple(_variable(v) for v in raw.get("variables", ()) or ())
    widgets = tuple(
        _widget(
            w,
            origin=origin,
            issues=issues,
            allowed_widget_types=allowed_widget_types,
            allowed_datasources=allowed_datasources,
        )
        for w in raw.get("widgets", ()) or ()
    )
    if issues:
        raise ReportCatalogError(issues)
    return ReportSpec(
        id=raw["id"],
        version=raw["version"],
        name=raw["name"],
        description=raw.get("description", ""),
        time_range=time_range,
        variables=variables,
        widgets=widgets,
        tags=tuple(raw.get("tags", ()) or ()),
    )


def load_report_catalog(
    root: Path,
    *,
    schema_path: Path | None = None,
    allowed_widget_types: frozenset[str] | None = None,
    allowed_datasources: frozenset[str] | None = None,
) -> tuple[ReportSpec, ...]:
    """Load and validate every ``*.yaml`` file under ``root`` (non-recursive).

    Files under ``schema/`` are skipped. Duplicate report ids across the
    loaded files raise :class:`ReportCatalogError`. Returns the specs in
    filename order for deterministic composition.
    """
    if not root.exists():
        return ()
    issues: list[ReportCatalogIssue] = []
    seen_ids: dict[str, str] = {}
    specs: list[ReportSpec] = []
    for path in sorted(root.iterdir()):
        if path.is_dir() or path.suffix.lower() not in (".yaml", ".yml"):
            continue
        origin = str(path)
        try:
            raw = _load_single(path)
        except ValueError as exc:
            issues.append(ReportCatalogIssue(origin, str(exc)))
            continue
        try:
            spec = load_report_from_mapping(
                raw,
                schema_path=schema_path,
                allowed_widget_types=allowed_widget_types,
                allowed_datasources=allowed_datasources,
                origin=origin,
            )
        except ReportCatalogError as exc:
            issues.extend(exc.issues)
            continue
        if spec.id in seen_ids:
            issues.append(
                ReportCatalogIssue(
                    origin,
                    f"duplicate report id {spec.id!r} (also in {seen_ids[spec.id]!r})",
                )
            )
            continue
        seen_ids[spec.id] = origin
        specs.append(spec)
    if issues:
        raise ReportCatalogError(issues)
    return tuple(specs)


# ---- internals ----------------------------------------------------------


def _validator(schema_path: Path | None) -> Draft202012Validator:
    path = schema_path or _DEFAULT_SCHEMA_PATH
    with path.open("r", encoding="utf-8") as fh:
        schema = yaml.safe_load(fh)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _load_single(path: Path) -> Mapping[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        documents = list(yaml.safe_load_all(fh))
    if not documents:
        raise ValueError("empty YAML file")
    if len(documents) > 1:
        raise ValueError("expected a single YAML document per report file")
    doc = documents[0]
    if not isinstance(doc, Mapping):
        raise ValueError(f"expected a mapping at document root, got {type(doc).__name__}")
    return doc


def _time_range(raw: Mapping[str, Any]) -> TimeRange:
    if "since" in raw and "until" in raw:
        return TimeRange(since=_parse_iso(raw["since"]), until=_parse_iso(raw["until"]))
    if "since" in raw:
        return TimeRange(since=_parse_iso(raw["since"]))
    duration_key = "relative_duration" if "relative_duration" in raw else "last"
    if duration_key in raw:
        return TimeRange(relative_duration=_parse_duration(raw[duration_key]))
    raise ValueError("time_range must supply since/until, since, or relative_duration/last")


def _parse_iso(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"expected ISO-8601 string, got {type(value).__name__}")
    # datetime.fromisoformat accepts "...Z" from 3.11+.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_duration(value: Any) -> timedelta:
    if not isinstance(value, str):
        raise ValueError(f"expected duration string, got {type(value).__name__}")
    match = _DURATION_RE.match(value)
    if match is None:
        raise ValueError(f"invalid duration {value!r}; expected e.g. '1d', '30m'")
    count = int(match.group(1))
    kwargs = {_DURATION_UNITS[match.group(2)]: count}
    return timedelta(**kwargs)


def _variable(raw: Mapping[str, Any]) -> Variable:
    return Variable(
        name=raw["name"],
        default=raw.get("default"),
        values=tuple(raw.get("values", ()) or ()),
        description=raw.get("description", ""),
    )


def _widget(
    raw: Mapping[str, Any],
    *,
    origin: str,
    issues: list[ReportCatalogIssue],
    allowed_widget_types: frozenset[str] | None,
    allowed_datasources: frozenset[str] | None,
) -> WidgetSpec:
    widget_type = raw["type"]
    if allowed_widget_types is not None and widget_type not in allowed_widget_types:
        # Group is not in the widget registry (engine special-cased) but
        # it is a legal widget type.
        if widget_type != "group":
            issues.append(
                ReportCatalogIssue(
                    origin,
                    f"widget {raw['id']!r}: unknown widget type {widget_type!r}",
                )
            )
    query = None
    if "query" in raw and raw["query"] is not None:
        query_raw = raw["query"]
        if allowed_datasources is not None and query_raw["datasource"] not in allowed_datasources:
            issues.append(
                ReportCatalogIssue(
                    origin,
                    f"widget {raw['id']!r}: unknown datasource {query_raw['datasource']!r}",
                )
            )
        query = QuerySpec(
            datasource=query_raw["datasource"],
            parameters=dict(query_raw.get("parameters", {}) or {}),
        )
    children = tuple(
        _widget(
            child,
            origin=origin,
            issues=issues,
            allowed_widget_types=allowed_widget_types,
            allowed_datasources=allowed_datasources,
        )
        for child in raw.get("children", ()) or ()
    )
    return WidgetSpec(
        id=raw["id"],
        type=widget_type,
        title=raw["title"],
        query=query,
        options=dict(raw.get("options", {}) or {}),
        children=children,
    )


__all__ = [
    "ReportCatalogError",
    "ReportCatalogIssue",
    "default_report_schema_path",
    "load_report_catalog",
    "load_report_from_mapping",
]
