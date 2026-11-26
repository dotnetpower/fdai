"""Deterministic, review-only report-line draft generation."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fdai_service_contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    ReportingLineCandidate,
    ReportingLineDirectory,
    ReportingLineDirectoryComparison,
    ReportingLineDraftArtifact,
    ReportingLineDraftOutcome,
    ReportingLineDraftStore,
    ReportingLineExtractionSource,
    ReportingLineManagerObservation,
    ReportingLineManagerStatus,
    ReportingLinePerson,
    ReportingLineResolvedIdentity,
    ReportingLineSourceSpan,
    StructuralUnit,
    UploadSession,
    reporting_line_candidate_id,
)

_EXPLICIT_EDGE = re.compile(
    r"^(?:subject|employee|직원|구성원)\s*:\s*([^;\r\n]{1,128})\s*;\s*"
    r"(?:manager|reports_to|관리자|보고 대상)\s*:\s*([^;\r\n]{1,128})\s*$",
    re.IGNORECASE,
)
_TABLE_CELL = re.compile(r"^(?P<table>.+)/(?:row:(?P<row>\d+)/cell:(?P<cell>\d+))$")
_SHEET_CELL = re.compile(r"^(?P<table>xlsx/sheet:\d+)/cell:(?P<column>[A-Z]+)(?P<row>\d+)$")
_SUBJECT_HEADERS = frozenset({"subject", "employee", "direct report", "직원", "구성원"})
_MANAGER_HEADERS = frozenset({"manager", "reports to", "supervisor", "관리자", "보고 대상"})


@dataclass(frozen=True, slots=True)
class ReportLineGenerationBudget:
    """Hard ceilings for one reporting-line draft."""

    max_units: int = 5_000
    max_candidates: int = 1_000
    max_directory_lookups: int = 500

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or value < 1
            for value in (
                self.max_units,
                self.max_candidates,
                self.max_directory_lookups,
            )
        ):
            raise ValueError("reporting-line generation budgets MUST be positive")


@dataclass(frozen=True, slots=True)
class ExtractedReportingLine:
    """One grounded names-only edge before directory resolution."""

    subject_name: str
    manager_name: str
    source: ReportingLineExtractionSource
    citations: tuple[ReportingLineSourceSpan, ...]
    confidence: float


class ReportingLineInterpreter(Protocol):
    """Propose grounded ambiguous edges without activating or approving them."""

    async def interpret(self, envelope: DocumentEnvelope) -> tuple[ExtractedReportingLine, ...]: ...


class AbstainingReportingLineInterpreter:
    """Default model seam that never infers an organization relationship."""

    async def interpret(self, envelope: DocumentEnvelope) -> tuple[ExtractedReportingLine, ...]:
        del envelope
        return ()


class NullReportingLineDirectory:
    """Return unavailable identity evidence without guessing."""

    async def resolve(self, display_name: str) -> ReportingLineResolvedIdentity | None:
        del display_name
        return None

    async def manager_for(self, subject_oid: str) -> ReportingLineManagerObservation:
        del subject_oid
        return ReportingLineManagerObservation(status=ReportingLineManagerStatus.UNAVAILABLE)


class ReportLineBootstrapConsumer:
    """Extract grounded reporting edges and persist a review-only artifact."""

    purpose = DocumentPurpose.REPORT_LINE_BOOTSTRAP

    def __init__(
        self,
        *,
        directory: ReportingLineDirectory,
        store: ReportingLineDraftStore,
        interpreter: ReportingLineInterpreter | None = None,
        confidence_floor: float = 0.8,
        budget: ReportLineGenerationBudget | None = None,
    ) -> None:
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError("reporting-line confidence floor MUST be in [0, 1]")
        self._directory = directory
        self._store = store
        self._interpreter = interpreter or AbstainingReportingLineInterpreter()
        self._confidence_floor = confidence_floor
        self._budget = budget or ReportLineGenerationBudget()

    async def consume(
        self,
        *,
        session: UploadSession,
        envelope: DocumentEnvelope,
    ) -> tuple[str, ...]:
        """Generate one bounded draft without changing a reporting graph."""

        if len(envelope.units) > self._budget.max_units:
            return await self._store_abstention(
                session,
                envelope,
                "reporting-line source unit budget exceeded",
            )
        extracted = list(_deterministic_edges(envelope.units))
        if not extracted:
            extracted.extend(await self._interpreter.interpret(envelope))
        extracted = list(_dedupe_edges(extracted))
        if len(extracted) > self._budget.max_candidates:
            return await self._store_abstention(
                session,
                envelope,
                "reporting-line candidate budget exceeded",
            )
        identity_names = {
            name.strip().casefold()
            for edge in extracted
            for name in (edge.subject_name, edge.manager_name)
        }
        if len(identity_names) > self._budget.max_directory_lookups:
            return await self._store_abstention(
                session,
                envelope,
                "reporting-line directory lookup budget exceeded",
            )

        identity_cache: dict[str, ReportingLineResolvedIdentity | None] = {}
        manager_cache: dict[str, ReportingLineManagerObservation] = {}
        candidates: list[ReportingLineCandidate] = []
        abstained: list[ReportingLineCandidate] = []
        unresolved: dict[str, ReportingLinePerson] = {}
        warnings: list[str] = []
        for edge in extracted:
            subject = await self._person(edge.subject_name, identity_cache)
            manager = await self._person(edge.manager_name, identity_cache)
            comparison, directory_manager_oid = await self._comparison(
                subject,
                manager,
                manager_cache,
            )
            try:
                candidate = ReportingLineCandidate(
                    candidate_id=reporting_line_candidate_id(
                        subject=subject,
                        manager=manager,
                        relationship_kind="primary_manager",
                        effective_from=None,
                        effective_until=None,
                        citations=edge.citations,
                    ),
                    subject=subject,
                    manager=manager,
                    confidence=edge.confidence,
                    extraction_source=edge.source,
                    citations=edge.citations,
                    directory_manager_oid=directory_manager_oid,
                    directory_comparison=comparison,
                )
            except ValueError:
                warnings.append("one invalid self-reporting or malformed edge was held")
                continue
            reviewable = (
                candidate.subject.oid is not None
                and candidate.manager.oid is not None
                and candidate.confidence >= self._confidence_floor
                and candidate.directory_comparison is not ReportingLineDirectoryComparison.CONFLICT
            )
            (candidates if reviewable else abstained).append(candidate)
            for person in (subject, manager):
                if person.oid is None:
                    unresolved.setdefault(person.display_name.casefold(), person)

        if abstained:
            warnings.append(f"{len(abstained)} reporting-line candidate(s) require human review")
        if unresolved:
            warnings.append(
                f"{len(unresolved)} reporting-line person name(s) did not resolve exactly"
            )
        if not candidates:
            warnings.append("no reporting-line candidate was ready for confirmation")
        artifact = ReportingLineDraftArtifact(
            upload_id=session.upload_id,
            document_id=envelope.document_id,
            version_id=envelope.version_id,
            source_sha256=envelope.source_sha256,
            outcome=(
                ReportingLineDraftOutcome.DRAFTED
                if candidates
                else ReportingLineDraftOutcome.ABSTAINED
            ),
            candidates=tuple(candidates),
            abstained=tuple(abstained),
            unresolved_people=tuple(unresolved.values()),
            warnings=tuple(warnings),
        )
        await self._store.put(artifact)
        return artifact.warnings

    async def _person(
        self,
        display_name: str,
        cache: dict[str, ReportingLineResolvedIdentity | None],
    ) -> ReportingLinePerson:
        key = display_name.strip().casefold()
        if key not in cache:
            cache[key] = await self._directory.resolve(display_name)
        resolved = cache[key]
        return ReportingLinePerson(
            display_name=display_name.strip(),
            oid=resolved.oid if resolved is not None else None,
        )

    async def _comparison(
        self,
        subject: ReportingLinePerson,
        manager: ReportingLinePerson,
        cache: dict[str, ReportingLineManagerObservation],
    ) -> tuple[ReportingLineDirectoryComparison, str | None]:
        if subject.oid is None or manager.oid is None:
            return ReportingLineDirectoryComparison.NOT_CHECKED, None
        if subject.oid not in cache:
            cache[subject.oid] = await self._directory.manager_for(subject.oid)
        observation = cache[subject.oid]
        if observation.status is not ReportingLineManagerStatus.RESOLVED:
            return ReportingLineDirectoryComparison.UNAVAILABLE, None
        if observation.manager_oid is None:  # pragma: no cover - contract invariant
            return ReportingLineDirectoryComparison.UNAVAILABLE, None
        comparison = (
            ReportingLineDirectoryComparison.MATCHED
            if observation.manager_oid.casefold() == manager.oid.casefold()
            else ReportingLineDirectoryComparison.CONFLICT
        )
        return comparison, observation.manager_oid

    async def _store_abstention(
        self,
        session: UploadSession,
        envelope: DocumentEnvelope,
        warning: str,
    ) -> tuple[str, ...]:
        warnings = (warning, "no reporting-line candidate was ready for confirmation")
        await self._store.put(
            ReportingLineDraftArtifact(
                upload_id=session.upload_id,
                document_id=envelope.document_id,
                version_id=envelope.version_id,
                source_sha256=envelope.source_sha256,
                outcome=ReportingLineDraftOutcome.ABSTAINED,
                warnings=warnings,
            )
        )
        return warnings


def _deterministic_edges(
    units: Sequence[StructuralUnit],
) -> tuple[ExtractedReportingLine, ...]:
    edges: list[ExtractedReportingLine] = []
    for unit in units:
        for line_number, line in enumerate(unit.text.splitlines(), start=1):
            match = _EXPLICIT_EDGE.fullmatch(line.strip())
            if match is None:
                continue
            edges.append(
                ExtractedReportingLine(
                    subject_name=match.group(1).strip(),
                    manager_name=match.group(2).strip(),
                    source=ReportingLineExtractionSource.DETERMINISTIC,
                    citations=(
                        ReportingLineSourceSpan(
                            unit_id=unit.unit_id,
                            locator=f"{unit.locator}#line:{line_number}",
                            quote=line.strip()[:200],
                        ),
                    ),
                    confidence=1.0,
                )
            )
    edges.extend(_table_edges(units))
    return _dedupe_edges(edges)


def _table_edges(units: Sequence[StructuralUnit]) -> tuple[ExtractedReportingLine, ...]:
    rows: dict[tuple[str, str], dict[str, StructuralUnit]] = {}
    for unit in units:
        location = _cell_location(unit)
        if location is None:
            continue
        table, row, column = location
        rows.setdefault((table, row), {})[column] = unit

    headers: dict[str, tuple[str, str]] = {}
    edges: list[ExtractedReportingLine] = []
    for (table, row), cells in sorted(rows.items()):
        subject_column = next(
            (column for column, unit in cells.items() if _header(unit.text) in _SUBJECT_HEADERS),
            None,
        )
        manager_column = next(
            (column for column, unit in cells.items() if _header(unit.text) in _MANAGER_HEADERS),
            None,
        )
        if subject_column is not None and manager_column is not None:
            headers[table] = (subject_column, manager_column)
            continue
        columns = headers.get(table)
        if columns is None:
            continue
        subject_unit = cells.get(columns[0])
        manager_unit = cells.get(columns[1])
        if subject_unit is None or manager_unit is None:
            continue
        subject_name = subject_unit.text.strip()
        manager_name = manager_unit.text.strip()
        if not subject_name or not manager_name:
            continue
        edges.append(
            ExtractedReportingLine(
                subject_name=subject_name,
                manager_name=manager_name,
                source=ReportingLineExtractionSource.DETERMINISTIC,
                citations=(
                    ReportingLineSourceSpan(
                        unit_id=subject_unit.unit_id,
                        locator=f"{table}/row:{row}",
                        quote=f"{subject_name} | {manager_name}"[:200],
                    ),
                ),
                confidence=1.0,
            )
        )
    return tuple(edges)


def _cell_location(unit: StructuralUnit) -> tuple[str, str, str] | None:
    table = _TABLE_CELL.fullmatch(unit.locator)
    if table is not None:
        return table.group("table"), table.group("row"), table.group("cell")
    sheet = _SHEET_CELL.fullmatch(unit.locator)
    if sheet is not None:
        return sheet.group("table"), sheet.group("row"), sheet.group("column")
    return None


def _header(value: str) -> str:
    return " ".join(value.strip().casefold().replace("_", " ").split())


def _dedupe_edges(
    edges: Sequence[ExtractedReportingLine],
) -> tuple[ExtractedReportingLine, ...]:
    best: dict[tuple[str, str], ExtractedReportingLine] = {}
    for edge in edges:
        key = (edge.subject_name.strip().casefold(), edge.manager_name.strip().casefold())
        current = best.get(key)
        if current is None or edge.confidence > current.confidence:
            best[key] = edge
    return tuple(
        sorted(
            best.values(),
            key=lambda item: (
                item.subject_name.casefold(),
                item.manager_name.casefold(),
            ),
        )
    )


__all__ = [
    "AbstainingReportingLineInterpreter",
    "ExtractedReportingLine",
    "NullReportingLineDirectory",
    "ReportLineBootstrapConsumer",
    "ReportLineGenerationBudget",
    "ReportingLineInterpreter",
]
