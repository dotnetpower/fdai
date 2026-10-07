"""Rescan verification: a fix claim becomes ``fixed_verified`` only with equivalent coverage.

Absence of a finding after a fix proves the fix only when the rescan could have found it. For
each claimed issue the rescan must:

- target the exact commit the developer claimed;
- include every producer that reported the issue, with the same rules version or one that the
  rescan explicitly declares as superseding the baseline version;
- report that each such run completed and was not truncated;
- list the issue's fix-site file among analyzed paths (or the operator asserted full-repository
  analysis for that run);
- use the same weakness-class catalog major version.

When any condition fails the verdict is ``inconclusive`` with reasons. When coverage is
equivalent, the verdict is ``still_present`` if the root cause matches a rescan issue and
``fixed_verified`` otherwise. Root-cause matching is conservative: same issue id, or same weakness
class and file (and symbol when both scans know it), or same package and any shared advisory.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from fdai.core.security.code_findings.models import CodeSecurityIssue
from fdai.core.security.code_findings.result_import import ClaimStatus, IssueClaim

_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_RESCANNED = (
    ClaimStatus.FIXED_CLAIMED,
    ClaimStatus.MITIGATED_CLAIMED,
    ClaimStatus.STALE_OR_ALREADY_FIXED,
)


class FixVerdict(StrEnum):
    FIXED_VERIFIED = "fixed_verified"
    STILL_PRESENT = "still_present"
    INCONCLUSIVE = "inconclusive"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ProducerRun:
    """One producer's run inside a scan, as recorded in a coverage receipt."""

    producer: str
    rules_version: str
    completed: bool | None
    truncated: bool
    analyzed_paths: frozenset[str] = frozenset()
    full_repository: bool = False
    supersedes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ScanCoverageReceipt:
    revision: str
    catalog_versions: Mapping[str, str]
    runs: tuple[ProducerRun, ...]

    def __post_init__(self) -> None:
        if _REVISION.fullmatch(self.revision) is None:
            raise ValueError("receipt revision must be a full lowercase commit id")

    def run_for(self, producer: str) -> ProducerRun | None:
        return next((run for run in self.runs if run.producer == producer), None)


@dataclass(frozen=True, slots=True)
class BaselineIssue:
    """The parts of a baseline issue that rescan matching needs, stored at export time."""

    issue_id: str
    weakness_class: str
    path: str
    symbol: str | None
    producers: tuple[str, ...]
    package: str | None = None
    advisory_ids: tuple[str, ...] = ()

    @classmethod
    def from_issue(cls, issue: CodeSecurityIssue) -> BaselineIssue:
        return cls(
            issue_id=issue.issue_id,
            weakness_class=issue.weakness_class,
            path=issue.fix_site.path,
            symbol=issue.fix_site.symbol,
            producers=issue.producers,
            package=issue.package,
            advisory_ids=issue.advisory_ids,
        )


@dataclass(frozen=True, slots=True)
class FixVerification:
    issue_id: str
    claim: ClaimStatus
    verdict: FixVerdict
    reasons: tuple[str, ...] = field(default=())


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def coverage_gaps(
    issue: BaselineIssue, baseline: ScanCoverageReceipt, rescan: ScanCoverageReceipt
) -> tuple[str, ...]:
    """Return why ``rescan`` cannot prove the absence of ``issue``; empty means equivalent."""
    gaps: list[str] = []
    base_class = baseline.catalog_versions.get("weakness_classes", "")
    if _major(rescan.catalog_versions.get("weakness_classes", "")) != _major(base_class):
        gaps.append("weakness-class catalog major version differs")
    for producer in issue.producers:
        before = baseline.run_for(producer)
        after = rescan.run_for(producer)
        if after is None:
            gaps.append(f"{producer}: no rescan run")
            continue
        if (
            before is not None
            and after.rules_version != before.rules_version
            and (before.rules_version not in after.supersedes)
        ):
            gaps.append(f"{producer}: rules version changed without declared supersession")
        if after.completed is not True:
            gaps.append(f"{producer}: completion not reported")
        if after.truncated:
            gaps.append(f"{producer}: rescan truncated")
        if not after.full_repository and issue.path not in after.analyzed_paths:
            gaps.append(f"{producer}: {issue.path} not among analyzed paths")
    return tuple(gaps)


def _still_present(issue: BaselineIssue, rescan_issues: Sequence[CodeSecurityIssue]) -> bool:
    for candidate in rescan_issues:
        if candidate.issue_id == issue.issue_id:
            return True
        if issue.advisory_ids:
            if candidate.package == issue.package and set(candidate.advisory_ids) & set(
                issue.advisory_ids
            ):
                return True
            continue
        if candidate.weakness_class != issue.weakness_class:
            continue
        if candidate.fix_site.path != issue.path:
            continue
        if issue.symbol and candidate.fix_site.symbol and issue.symbol != candidate.fix_site.symbol:
            continue
        return True
    return False


def verify_fix_claims(
    claims: Sequence[IssueClaim],
    baseline_issues: Mapping[str, BaselineIssue],
    baseline: ScanCoverageReceipt,
    rescan: ScanCoverageReceipt,
    rescan_issues: Sequence[CodeSecurityIssue],
    claimed_revision: str,
) -> tuple[FixVerification, ...]:
    """Return one verdict per claim. Claims that need no rescan are ``not_applicable``."""
    if any(issue.revision != rescan.revision for issue in rescan_issues):
        raise ValueError("rescan issues must target the rescan receipt revision")
    results: list[FixVerification] = []
    for claim in claims:
        if claim.status not in _RESCANNED:
            results.append(FixVerification(claim.issue_id, claim.status, FixVerdict.NOT_APPLICABLE))
            continue
        issue = baseline_issues.get(claim.issue_id)
        if issue is None:
            results.append(
                FixVerification(
                    claim.issue_id,
                    claim.status,
                    FixVerdict.INCONCLUSIVE,
                    ("unknown baseline issue",),
                )
            )
            continue
        gaps = list(coverage_gaps(issue, baseline, rescan))
        if rescan.revision != claimed_revision:
            gaps.insert(0, "rescan does not target the claimed commit")
        if gaps:
            results.append(
                FixVerification(claim.issue_id, claim.status, FixVerdict.INCONCLUSIVE, tuple(gaps))
            )
        elif _still_present(issue, rescan_issues):
            results.append(
                FixVerification(
                    claim.issue_id,
                    claim.status,
                    FixVerdict.STILL_PRESENT,
                    ("root cause still reported by an equivalent rescan",),
                )
            )
        else:
            results.append(FixVerification(claim.issue_id, claim.status, FixVerdict.FIXED_VERIFIED))
    return tuple(results)


__all__ = [
    "BaselineIssue",
    "FixVerdict",
    "FixVerification",
    "ProducerRun",
    "ScanCoverageReceipt",
    "coverage_gaps",
    "verify_fix_claims",
]
