"""Deterministic, review-only stewardship draft generation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from fdai_service_contracts import (
    DocumentEnvelope,
    DocumentPurpose,
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    HandoverDraftStore,
    HandoverMapping,
    HandoverPerson,
    HandoverSourceSpan,
    ResolvedStewardIdentity,
    StewardDuty,
    StewardKind,
    StewardPersonDirectory,
    StewardResponsibility,
    StewardshipAgentInput,
    StewardshipDraft,
    StewardshipInput,
    StewardshipSubject,
    UploadSession,
)

_AGENT_DOMAINS: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("Odin", ("prioritization", "arbitration", "tie-break", "steering"), 1.0),
    ("Thor", ("deployment", "release", "run the runbook", "rollout"), 0.8),
    ("Forseti", ("change approval", "change advisory", "safety review"), 1.0),
    ("Huginn", ("alert intake", "event triage", "incident intake"), 1.0),
    ("Heimdall", ("monitoring", "observability", "anomaly", "drift"), 1.0),
    ("Vidar", ("rollback", "disaster recovery", "failover", "recovery"), 1.0),
    ("Var", ("approver", "sign-off", "authorize", "dual control"), 1.0),
    ("Bragi", ("status report", "stakeholder comms", "communications"), 1.0),
    ("Saga", ("audit", "compliance", "record keeping", "evidence"), 1.0),
    ("Mimir", ("policy", "standards", "rule owner", "control catalog"), 1.0),
    ("Muninn", ("runbook owner", "knowledge base", "documentation owner"), 1.0),
    ("Norns", ("postmortem", "retrospective", "lessons learned", "rca owner"), 1.0),
    ("Njord", ("cost", "finops", "budget", "spend"), 1.0),
    ("Freyr", ("capacity", "sizing", "performance", "scaling"), 1.0),
    ("Loki", ("chaos", "resilience testing", "fault injection", "game day"), 1.0),
)
_AGENT_NAMES = tuple(item[0] for item in _AGENT_DOMAINS)
_STRUCTURED_ASSIGNMENT = re.compile(
    r"^agent\s*:\s*([^;]+)\s*;\s*responsibility\s*:\s*(accountable|informed)\s*;\s*"
    r"subject\s*:\s*(user|group)\s*;\s*identity\s*:\s*([^;\r\n]{1,128})\s*$",
    re.IGNORECASE,
)
_OWNER_NAME = re.compile(
    r"(?i:owner|accountable|responsible|lead|owned by|primary)\s*[:\-]?\s*"
    r"([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})"
)
_NAME = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")


@dataclass(frozen=True, slots=True)
class HandoverGenerationBudget:
    """Hard ceilings for one deterministic handover draft attempt."""

    max_units: int = 2_000
    max_lines: int = 10_000
    max_candidates: int = 2_000
    max_directory_lookups: int = 500
    max_yaml_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if any(
            value < 1
            for value in (
                self.max_units,
                self.max_lines,
                self.max_candidates,
                self.max_directory_lookups,
                self.max_yaml_bytes,
            )
        ):
            raise ValueError("handover generation budgets MUST be positive")


class NullStewardPersonDirectory:
    """Explicitly leave every person unresolved when Graph is unavailable."""

    async def resolve(self, _display_name: str) -> ResolvedStewardIdentity | None:
        return None


class HandoverBootstrapConsumer:
    """Generate and store a grounded draft without applying stewardship changes."""

    purpose = DocumentPurpose.HANDOVER_BOOTSTRAP

    def __init__(
        self,
        *,
        directory: StewardPersonDirectory,
        store: HandoverDraftStore,
        stewardship: StewardshipInput | None,
        confidence_floor: float = 0.6,
        budget: HandoverGenerationBudget | None = None,
    ) -> None:
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError("handover confidence floor MUST be in [0, 1]")
        self._directory = directory
        self._store = store
        self._stewardship = stewardship
        self._confidence_floor = confidence_floor
        self._budget = budget or HandoverGenerationBudget()

    async def consume(
        self, *, session: UploadSession, envelope: DocumentEnvelope
    ) -> tuple[str, ...]:
        if self._stewardship is None:
            unavailable_warnings = (
                "current stewardship input is unavailable; nothing was drafted",
            )
            await self._store.put(
                HandoverDraftArtifact(
                    upload_id=session.upload_id,
                    document_id=envelope.document_id,
                    version_id=envelope.version_id,
                    draft=StewardshipDraft(
                        outcome=HandoverDraftOutcome.ABSTAINED,
                        unmapped_agents=_AGENT_NAMES,
                        warnings=unavailable_warnings,
                    ),
                    yaml="# handover draft unavailable: current stewardship input is missing\n",
                )
            )
            return unavailable_warnings
        budget_reason, candidates = _bounded_candidates(
            envelope,
            budget=self._budget,
        )
        if budget_reason is not None:
            budget_warnings = (budget_reason, "nothing was drafted")
            await self._store.put(
                _artifact(
                    session=session,
                    envelope=envelope,
                    draft=StewardshipDraft(
                        outcome=HandoverDraftOutcome.ABSTAINED,
                        unmapped_agents=_unmapped_agents(self._stewardship, ()),
                        warnings=budget_warnings,
                    ),
                    stewardship=self._stewardship,
                    max_yaml_bytes=self._budget.max_yaml_bytes,
                )
            )
            return budget_warnings
        resolved: list[HandoverMapping] = []
        cache: dict[str, ResolvedStewardIdentity | None] = {}
        for mapping in candidates:
            key = mapping.person.display_name.casefold()
            if key not in cache:
                if len(cache) >= self._budget.max_directory_lookups:
                    lookup_warnings = (
                        "handover directory lookup budget exceeded",
                        "nothing was drafted",
                    )
                    await self._store.put(
                        _artifact(
                            session=session,
                            envelope=envelope,
                            draft=StewardshipDraft(
                                outcome=HandoverDraftOutcome.ABSTAINED,
                                unmapped_agents=_unmapped_agents(self._stewardship, ()),
                                warnings=lookup_warnings,
                            ),
                            stewardship=self._stewardship,
                            max_yaml_bytes=self._budget.max_yaml_bytes,
                        )
                    )
                    return lookup_warnings
                cache[key] = await self._directory.resolve(mapping.person.display_name)
            identity = cache[key]
            person = mapping.person.model_copy(
                update={
                    "kind": identity.kind if identity else mapping.person.kind,
                    "oid": identity.oid if identity else None,
                }
            )
            resolved.append(mapping.model_copy(update={"person": person}))
        mappings = tuple(item for item in resolved if item.confidence >= self._confidence_floor)
        abstained = tuple(item for item in resolved if item.confidence < self._confidence_floor)
        unresolved = tuple(
            {
                item.person.display_name.casefold(): item.person
                for item in mappings
                if item.person.unresolved
            }.values()
        )
        unmapped = _unmapped_agents(self._stewardship, mappings)
        warnings = _warnings(mappings, abstained, unresolved, unmapped)
        draft = StewardshipDraft(
            outcome=(HandoverDraftOutcome.DRAFTED if mappings else HandoverDraftOutcome.ABSTAINED),
            mappings=mappings,
            abstained=abstained,
            unresolved_people=unresolved,
            unmapped_agents=unmapped,
            warnings=warnings,
        )
        artifact = _artifact(
            session=session,
            envelope=envelope,
            draft=draft,
            stewardship=self._stewardship,
            max_yaml_bytes=self._budget.max_yaml_bytes,
        )
        await self._store.put(artifact)
        return warnings


def stewardship_input_from_environment(environ: Mapping[str, str]) -> StewardshipInput | None:
    """Build a bounded current-map snapshot from worker-owned deployment inputs."""
    maintainers = tuple(
        value.strip() for value in environ.get("FDAI_MAINTAINERS", "").split(",") if value.strip()
    )
    raw_bindings = {
        agent: environ.get(f"FDAI_STEWARD_{agent.upper()}", "").strip() for agent in _AGENT_NAMES
    }
    if not maintainers and not any(raw_bindings.values()):
        return None
    if not maintainers:
        raise ValueError("FDAI_MAINTAINERS is required when stewardship bindings are configured")
    try:
        version = int(environ.get("FDAI_STEWARDSHIP_VERSION", "1"))
    except ValueError as exc:
        raise ValueError("FDAI_STEWARDSHIP_VERSION MUST be 1 or 2") from exc
    if version not in {1, 2}:
        raise ValueError("FDAI_STEWARDSHIP_VERSION MUST be 1 or 2")
    schema_version = cast(Literal[1, 2], version)
    agents = tuple(
        StewardshipAgentInput(
            agent_name=agent,
            stewards=_parse_stewards(raw_bindings[agent], version=schema_version),
        )
        for agent in _AGENT_NAMES
    )
    canonical = json.dumps(
        {
            "version": schema_version,
            "maintainers": maintainers,
            "agents": {
                item.agent_name: [subject.model_dump(mode="json") for subject in item.stewards]
                for item in agents
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return StewardshipInput(
        version=schema_version,
        revision=hashlib.sha256(canonical.encode()).hexdigest()[:16],
        maintainers=maintainers,
        agents=agents,
    )


def _parse_stewards(value: str, *, version: int) -> tuple[StewardshipSubject, ...]:
    subjects: list[StewardshipSubject] = []
    for token in (item.strip() for item in value.split(",") if item.strip()):
        fields = tuple(item.strip() for item in token.split(":"))
        if len(fields) not in {2, 3, 4}:
            raise ValueError("FDAI_STEWARD_<AGENT> entries MUST contain 2 to 4 fields")
        kind, oid = fields[:2]
        responsibility = fields[2] if len(fields) >= 3 else "accountable"
        duty = fields[3] if len(fields) == 4 else None
        if version == 2 and responsibility == "accountable" and duty is None:
            raise ValueError("schema v2 accountable stewardship entries MUST declare a duty")
        subjects.append(
            StewardshipSubject(
                kind=StewardKind(kind),
                oid=oid,
                responsibility=StewardResponsibility(responsibility),
                duty=StewardDuty(duty) if duty is not None else None,
            )
        )
    return tuple(subjects)


def _bounded_candidates(
    envelope: DocumentEnvelope,
    *,
    budget: HandoverGenerationBudget,
) -> tuple[str | None, tuple[HandoverMapping, ...]]:
    if len(envelope.units) > budget.max_units:
        return "handover structural unit budget exceeded", ()
    candidates: list[HandoverMapping] = []
    line_number = 0
    for unit in envelope.units:
        for source_line in unit.text.splitlines():
            line_number += 1
            if line_number > budget.max_lines:
                return "handover source line budget exceeded", ()
            candidates.extend(
                _extract_line(source_line.strip(), str(envelope.document_id), line_number)
            )
            if len(candidates) > budget.max_candidates:
                return "handover candidate budget exceeded", ()
    return None, tuple(candidates)


def _extract_line(line: str, doc_id: str, line_number: int) -> tuple[HandoverMapping, ...]:
    if not line:
        return ()
    structured = _STRUCTURED_ASSIGNMENT.fullmatch(line)
    if structured is not None:
        requested_agent = structured.group(1).strip().casefold()
        agent = next(
            (name for name in _AGENT_NAMES if name.casefold() == requested_agent),
            None,
        )
        if agent is None:
            return ()
        return (
            HandoverMapping(
                agent_name=agent,
                person=HandoverPerson(
                    display_name=structured.group(4).strip(),
                    kind=StewardKind(structured.group(3).casefold()),
                ),
                responsibility=StewardResponsibility(structured.group(2).casefold()),
                confidence=1.0,
                citations=(HandoverSourceSpan(doc_id=doc_id, line=line_number, quote=line[:200]),),
                rationale="explicit structured assignment",
            ),
        )
    lowered = line.casefold()
    person_match = _OWNER_NAME.search(line) or _NAME.search(line)
    if person_match is None:
        return ()
    person = HandoverPerson(display_name=person_match.group(1).strip().rstrip(" .,;:"))
    explicit_person = _OWNER_NAME.search(line) is not None
    explicit_responsibility = any(
        marker in lowered
        for marker in ("accountable", "responsible", "owner", "owned by", "lead", "(a)", "(r)")
    )
    responsibility = (
        StewardResponsibility.INFORMED
        if any(marker in lowered for marker in ("informed", "consulted", "(i)", "(c)"))
        else StewardResponsibility.ACCOUNTABLE
    )
    mappings: list[HandoverMapping] = []
    for agent, keywords, specificity in _AGENT_DOMAINS:
        matches = tuple(keyword for keyword in keywords if keyword in lowered)
        if not matches:
            continue
        confidence = min(
            1.0,
            0.45
            + specificity * 0.25
            + (0.2 if explicit_responsibility else 0.0)
            + (0.15 if explicit_person else 0.0),
        )
        mappings.append(
            HandoverMapping(
                agent_name=agent,
                person=person,
                responsibility=responsibility,
                confidence=round(confidence, 3),
                citations=(HandoverSourceSpan(doc_id=doc_id, line=line_number, quote=line[:200]),),
                rationale=f"domain keyword {max(matches, key=len)!r} -> {agent}",
            )
        )
    return tuple(mappings)


def _warnings(
    mappings: tuple[HandoverMapping, ...],
    abstained: tuple[HandoverMapping, ...],
    unresolved: tuple[HandoverPerson, ...],
    unmapped: tuple[str, ...],
) -> tuple[str, ...]:
    warnings: list[str] = []
    if abstained:
        warnings.append(f"{len(abstained)} candidate mapping(s) require human review")
    if unresolved:
        warnings.append(f"{len(unresolved)} person/team name(s) did not resolve")
    if unmapped:
        warnings.append(f"{len(unmapped)} agent(s) have no accountable owner")
    if not mappings:
        warnings.append("no mapping cleared the confidence floor; nothing was drafted")
    return tuple(warnings)


def _artifact(
    *,
    session: UploadSession,
    envelope: DocumentEnvelope,
    draft: StewardshipDraft,
    stewardship: StewardshipInput,
    max_yaml_bytes: int,
) -> HandoverDraftArtifact:
    rendered = _render_yaml(draft, stewardship)
    if len(rendered.encode("utf-8")) > max_yaml_bytes:
        warning = "handover rendered YAML budget exceeded"
        draft = StewardshipDraft(
            outcome=HandoverDraftOutcome.ABSTAINED,
            unmapped_agents=_unmapped_agents(stewardship, ()),
            warnings=(warning, "nothing was drafted"),
        )
        rendered = _render_yaml(draft, stewardship)
        if len(rendered.encode("utf-8")) > max_yaml_bytes:
            rendered = "# handover draft unavailable: rendered YAML budget exceeded\n"
    return HandoverDraftArtifact(
        upload_id=session.upload_id,
        document_id=envelope.document_id,
        version_id=envelope.version_id,
        draft=draft,
        yaml=rendered,
    )


def _unmapped_agents(
    stewardship: StewardshipInput,
    mappings: tuple[HandoverMapping, ...],
) -> tuple[str, ...]:
    accountable = {
        item.agent_name
        for item in stewardship.agents
        if any(
            subject.responsibility is StewardResponsibility.ACCOUNTABLE for subject in item.stewards
        )
    }
    accountable.update(
        item.agent_name
        for item in mappings
        if item.responsibility is StewardResponsibility.ACCOUNTABLE
    )
    return tuple(name for name in _AGENT_NAMES if name not in accountable)


def _render_yaml(draft: StewardshipDraft, stewardship: StewardshipInput) -> str:
    current = {item.agent_name: item for item in stewardship.agents}
    by_agent: dict[str, list[HandoverMapping]] = {name: [] for name in _AGENT_NAMES}
    for mapping in draft.mappings:
        if mapping.person.oid is not None:
            by_agent[mapping.agent_name].append(mapping)
    lines = [
        "# FDAI agent-stewardship DRAFT generated from an ingested handover document.",
        "# Review every mapping and citation before merging. This draft is never auto-applied.",
        f"# outcome: {draft.outcome.value}",
        f"# baseline revision: {stewardship.revision}",
        "stewardship:",
        f"  version: {stewardship.version}",
        "  maintainers:",
        *(f'    - oid: "{oid}"' for oid in stewardship.maintainers),
        "  channels: {}",
        "  escalation:",
        f"    hop_timeout_seconds: {stewardship.hop_timeout_seconds}",
        "  thresholds:",
        f"    over_assigned_max: {stewardship.over_assigned_max}",
        "  agents:",
    ]
    for agent in _AGENT_NAMES:
        existing = current.get(agent, StewardshipAgentInput(agent_name=agent))
        lines.append(f"    {agent}:")
        subjects = list(existing.stewards)
        subjects.extend(
            StewardshipSubject(
                kind=mapping.person.kind,
                oid=mapping.person.oid or "",
                responsibility=mapping.responsibility,
            )
            for mapping in by_agent[agent]
        )
        subjects = list(dict.fromkeys(subjects))
        if subjects:
            lines.append("      stewards:")
            for subject in subjects:
                duty = f", duty: {subject.duty.value}" if subject.duty is not None else ""
                lines.append(
                    f'        - {{ kind: {subject.kind.value}, id: "{subject.oid}", '
                    f"responsibility: {subject.responsibility.value}{duty} }}"
                )
        if existing.accept_autonomous_reason is not None:
            lines.extend(
                (
                    "      accept_autonomous:",
                    f'        reason: "{existing.accept_autonomous_reason}"',
                )
            )
        elif not subjects:
            lines.append("      stewards: []   # TODO: human review required")
    for mapping in draft.mappings:
        citation = mapping.citations[0]
        lines.append(
            f"# candidate: {mapping.agent_name} <- {mapping.person.display_name} "
            f"({citation.doc_id}:L{citation.line})"
        )
    return "\n".join(lines) + "\n"
