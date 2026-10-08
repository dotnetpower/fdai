"""Typed records for code-security findings, from raw scanner occurrence to fix group.

The hierarchy keeps one user-visible severity per root cause:

- :class:`Occurrence` - one result from one scanner, lane, and layer. It keeps only the
  producer's own severity as ``source_severity`` and is never shown as an issue.
- :class:`Instance` - one source-to-sink path (or one dependency layer) of a root cause, with its
  own facts and severity range.
- :class:`CodeSecurityIssue` - one root cause at one fix site. Its severity is derived from its
  instances and is the only severity users see.
- :class:`FixGroup` - issues that one coherent change fixes together.

Every text field that originated in scanned code or a scanner report is untrusted data; parsers
sanitize it before it reaches these records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from fdai.rule_catalog.code_security import (
    AttackComplexity,
    AttackVector,
    AutofixEligibility,
    Confidence,
    Exposure,
    FixClass,
    Impact,
    Priority,
    PrivilegesRequired,
    RemediationDepth,
    SeverityBand,
    UserInteraction,
)


class Lane(StrEnum):
    """Detection lane that produced an occurrence."""

    DETERMINISTIC = "deterministic"
    LLM_LENS = "llm_lens"
    EXTERNAL = "external"


class SeverityMethod(StrEnum):
    FACT_RUBRIC = "fact_rubric"
    ADVISORY_SCORE = "advisory_score"


class TestFeasibility(StrEnum):
    AVAILABLE = "available"
    NO_HARNESS = "no_harness"
    UNKNOWN = "unknown"


UNDETERMINED = "undetermined"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A repository-relative location. ``path`` is normalized POSIX and never absolute."""

    path: str
    start_line: int | None = None
    end_line: int | None = None
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class FlowStep:
    path: str
    line: int | None


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One normalized scanner result. ``message`` is sanitized untrusted text."""

    occurrence_id: str
    producer: str
    producer_version: str
    lane: Lane
    scan_digest: str
    revision: str
    rule_id: str
    location: SourceLocation
    cwe_ids: tuple[int, ...] = ()
    tags: tuple[str, ...] = ()
    source_severity: str = ""
    message: str = ""
    code_flow: tuple[FlowStep, ...] = ()
    advisory_ids: tuple[str, ...] = ()
    package: str | None = None
    package_version: str | None = None
    advisory_score: float | None = None
    fingerprints: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class InstanceFacts:
    """Verified facts for one instance. ``None`` means the fact is unknown.

    Facts come from deterministic verifiers, inventory, or authorized human input, never from a
    scanner's free text. ``evidence_refs`` cites where each verified fact came from.
    """

    impact: Impact | None = None
    attack_vector: AttackVector | None = None
    attack_complexity: AttackComplexity | None = None
    privileges_required: PrivilegesRequired | None = None
    user_interaction: UserInteraction | None = None
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SeverityAssessment:
    """Severity for one instance or issue.

    ``label`` is a band when ``floor`` and ``ceiling`` agree and ``undetermined`` otherwise.
    ``deciding_facts`` lists unknown facts whose verification can move the band.
    """

    label: str
    floor: SeverityBand
    ceiling: SeverityBand
    method: SeverityMethod
    floor_points: float
    ceiling_points: float
    unknown_facts: tuple[str, ...]
    deciding_facts: tuple[str, ...]
    rationale: str
    rubric_version: str

    @property
    def determined(self) -> bool:
        return self.label != UNDETERMINED


@dataclass(frozen=True, slots=True)
class Instance:
    instance_id: str
    source: FlowStep | None
    occurrence_ids: tuple[str, ...]
    facts: InstanceFacts
    severity: SeverityAssessment


@dataclass(frozen=True, slots=True)
class PriorityAssignment:
    priority: Priority
    due_days: int
    rule_id: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class CodeSecurityIssue:
    """One root cause at one fix site, with exactly one user-visible severity."""

    issue_id: str
    weakness_class: str
    title: str
    revision: str
    fix_site: SourceLocation
    severity: SeverityAssessment
    governing_instance_id: str
    confidence: Confidence
    exposure: Exposure
    priority: PriorityAssignment
    instances: tuple[Instance, ...]
    cwe_ids: tuple[int, ...]
    producers: tuple[str, ...]
    lanes: tuple[Lane, ...]
    occurrence_ids: tuple[str, ...]
    source_severities: tuple[tuple[str, str], ...]
    advisory_ids: tuple[str, ...] = ()
    package: str | None = None
    package_versions: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()
    known_exploited: bool = False
    code_flow: tuple[FlowStep, ...] = ()
    messages: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class ProjectRoot:
    """A buildable project inside the repository, supplied by acquisition or the operator."""

    path: str
    ecosystem: str
    targeted_test_command: str | None = None
    full_test_command: str | None = None
    generator_command: str | None = None


@dataclass(frozen=True, slots=True)
class FixGroup:
    group_id: str
    title: str
    weakness_class: str
    fix_class: FixClass
    autofix_eligibility: AutofixEligibility
    max_depth: RemediationDepth
    priority: Priority
    issue_ids: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    guidance: str
    project_root: str
    ecosystem: str
    targeted_test_command: str | None
    full_test_command: str | None
    test_feasibility: TestFeasibility
    order: int


__all__ = [
    "UNDETERMINED",
    "CodeSecurityIssue",
    "FixGroup",
    "FlowStep",
    "Instance",
    "InstanceFacts",
    "Lane",
    "Occurrence",
    "PriorityAssignment",
    "ProjectRoot",
    "SeverityAssessment",
    "SeverityMethod",
    "SourceLocation",
    "TestFeasibility",
]
