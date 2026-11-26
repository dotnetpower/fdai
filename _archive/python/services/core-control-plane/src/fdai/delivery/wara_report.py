"""Private local report exports and bounded import of native WARA collector context."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from fdai.core.reporting.formats import install_default_formats
from fdai.core.reporting.registry import FormatRegistry
from fdai.core.wara.models import WaraAssessmentRequest, WaraAssessmentResult
from fdai.core.wara.report import SUPPLEMENTAL_SOURCES, build_wara_report
from fdai.delivery.wara_office_formats import PptxFormatEncoder, XlsxFormatEncoder
from fdai.rule_catalog.schema.wara_assessment import WaraAssessmentCatalog

_COLLECTOR_FIELDS = ("advisory", "outages", "retirements", "supportTickets", "serviceHealth")
_SUBSCRIPTION = re.compile(r"(?i)^/subscriptions/([a-f0-9-]{36})(?:/|$)")
_MAXIMUM_BYTES = 16_777_216


def read_collector_context(
    path: Path, request: WaraAssessmentRequest
) -> tuple[dict[str, object], ...]:
    """Import counts only; an unsigned collector file cannot become assessment evidence."""

    try:
        with path.open("rb") as stream:
            body = stream.read(_MAXIMUM_BYTES + 1)
    except OSError as exc:
        raise ValueError("WARA collector context could not be read") from exc
    if len(body) > _MAXIMUM_BYTES:
        raise ValueError("WARA collector context exceeds the byte limit")
    try:
        raw = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("WARA collector context is not valid JSON") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("scriptDetails"), dict):
        raise ValueError("WARA collector context requires collector scope metadata")
    details = raw["scriptDetails"]
    subscriptions = details.get("ImplicitSubscriptionIds")
    if subscriptions is None:
        subscriptions = details.get("SubscriptionIds")
    if isinstance(subscriptions, str):
        subscriptions = [subscriptions]
    if (
        not isinstance(subscriptions, list)
        or not subscriptions
        or any(not isinstance(value, str) for value in subscriptions)
    ):
        raise ValueError("WARA collector context subscription scope is invalid")
    expected = set()
    for resource in request.resources:
        match = _SUBSCRIPTION.match(resource.resource_id)
        if match is None:
            raise ValueError("WARA collector context requires exact ARM resource identities")
        expected.add(match.group(1).casefold())
    supplied = set()
    for value in subscriptions:
        match = _SUBSCRIPTION.fullmatch(value.rstrip("/"))
        if match is None:
            raise ValueError("WARA collector context subscription identity is invalid")
        supplied.add(match.group(1).casefold())
    if supplied != expected:
        raise ValueError("WARA collector context belongs to a different subscription scope")
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    rows: list[dict[str, object]] = []
    for source, field in zip(SUPPLEMENTAL_SOURCES, _COLLECTOR_FIELDS, strict=True):
        items = raw.get(field)
        if items is not None and not isinstance(items, (list, dict)):
            raise ValueError("WARA collector context collection shape is invalid")
        if isinstance(items, list) and (
            len(items) > 10_000 or any(not isinstance(item, dict) for item in items)
        ):
            raise ValueError("WARA collector context collection exceeds its contract")
        rows.append(
            {
                "source": source,
                "status": "unverified" if items is not None else "unavailable",
                "count": len(items)
                if isinstance(items, list)
                else 1
                if items is not None
                else None,
                "complete": False,
                "scope": "subscription_context",
                "source_digest": digest,
                "limitation": "collector_context_is_not_verified_recommendation_evidence",
            }
        )
    return tuple(rows)


class WaraFileReportSink:
    """Write all four formats from one immutable assessment into private local files."""

    def __init__(self, *, output_directory: Path, collector_context: Path | None = None) -> None:
        self._directory = output_directory
        self._collector_context = collector_context
        self._formats = install_default_formats(FormatRegistry())
        self._formats.register(XlsxFormatEncoder())
        self._formats.register(PptxFormatEncoder())

    async def write(
        self,
        result: WaraAssessmentResult,
        catalog: WaraAssessmentCatalog,
        request: WaraAssessmentRequest,
    ) -> None:
        await asyncio.to_thread(self._write, result, catalog, request)

    def _write(
        self,
        result: WaraAssessmentResult,
        catalog: WaraAssessmentCatalog,
        request: WaraAssessmentRequest,
    ) -> None:
        context = (
            read_collector_context(self._collector_context, request)
            if self._collector_context is not None
            else ()
        )
        report = build_wara_report(result, catalog, supplemental=context)
        encoded = {
            name: self._formats.get(name).encode(report) for name in ("json", "csv", "xlsx", "pptx")
        }
        self._directory.mkdir(parents=True, exist_ok=True)
        basename = "wara-" + result.result_digest.removeprefix("sha256:")
        for name, body in encoded.items():
            temporary: str | None = None
            try:
                with tempfile.NamedTemporaryFile(dir=self._directory, delete=False) as stream:
                    temporary = stream.name
                    stream.write(body)
                os.replace(temporary, self._directory / f"{basename}.{name}")
            finally:
                if temporary is not None and os.path.exists(temporary):
                    os.unlink(temporary)


__all__ = ["WaraFileReportSink", "read_collector_context"]
