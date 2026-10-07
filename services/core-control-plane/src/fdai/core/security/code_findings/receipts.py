"""Build and serialize scan coverage receipts and baseline issue snapshots.

Receipts come from ingested SARIF run metadata plus operator-asserted facts that SARIF cannot
carry reliably: the rules version per producer, whether a producer analyzed the whole repository,
and which earlier rules version a newer one supersedes. The operator's assertions are recorded in
the receipt, so a later reader can tell observed facts from asserted ones.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.core.security.code_findings.models import CodeSecurityIssue
from fdai.core.security.code_findings.sarif import SarifIngestResult
from fdai.core.security.code_findings.verification import (
    BaselineIssue,
    ProducerRun,
    ScanCoverageReceipt,
)


def build_receipt(
    revision: str,
    catalog_versions: Mapping[str, str],
    ingested: Sequence[SarifIngestResult],
    *,
    rules_versions: Mapping[str, str] | None = None,
    full_repository: frozenset[str] = frozenset(),
    supersedes: Mapping[str, frozenset[str]] | None = None,
    observed_completion: Mapping[str, bool] | None = None,
) -> ScanCoverageReceipt:
    """Merge every run per producer into one :class:`ProducerRun`.

    A producer counts as completed only if every one of its runs reported success, and as
    truncated if any run was truncated. Without an asserted rules version the tool version is used.
    ``observed_completion`` holds completion the FDAI sandbox observed itself; it overrides the
    producer's own report, and an observed failure also marks the run truncated.
    """
    merged: dict[str, dict[str, Any]] = {}
    for result in ingested:
        for run in result.runs:
            entry = merged.setdefault(
                run.producer,
                {"versions": set(), "completed": [], "truncated": False, "paths": set()},
            )
            entry["versions"].add(run.version)
            entry["completed"].append(run.execution_successful)
            entry["truncated"] = entry["truncated"] or run.truncated
            entry["paths"].update(run.analyzed_paths)
    runs = []
    for producer, entry in sorted(merged.items()):
        statuses = entry["completed"]
        completed = None if any(status is None for status in statuses) else all(statuses)
        observed = (observed_completion or {}).get(producer)
        if observed is not None:
            completed = observed
        asserted = (rules_versions or {}).get(producer)
        runs.append(
            ProducerRun(
                producer=producer,
                rules_version=asserted or "tool:" + "+".join(sorted(entry["versions"])),
                completed=completed,
                truncated=entry["truncated"] or observed is False,
                analyzed_paths=frozenset(entry["paths"]),
                full_repository=producer in full_repository,
                supersedes=(supersedes or {}).get(producer, frozenset()),
            )
        )
    return ScanCoverageReceipt(revision, dict(catalog_versions), tuple(runs))


def receipt_to_dict(receipt: ScanCoverageReceipt) -> dict[str, Any]:
    return {
        "revision": receipt.revision,
        "catalog_versions": dict(receipt.catalog_versions),
        "runs": [
            {
                "producer": run.producer,
                "rules_version": run.rules_version,
                "completed": run.completed,
                "truncated": run.truncated,
                "analyzed_paths": sorted(run.analyzed_paths),
                "full_repository": run.full_repository,
                "supersedes": sorted(run.supersedes),
            }
            for run in receipt.runs
        ],
    }


def receipt_from_dict(document: Mapping[str, Any]) -> ScanCoverageReceipt:
    return ScanCoverageReceipt(
        revision=str(document["revision"]),
        catalog_versions={str(k): str(v) for k, v in dict(document["catalog_versions"]).items()},
        runs=tuple(
            ProducerRun(
                producer=str(run["producer"]),
                rules_version=str(run["rules_version"]),
                completed=run["completed"] if isinstance(run["completed"], bool) else None,
                truncated=bool(run["truncated"]),
                analyzed_paths=frozenset(str(p) for p in run["analyzed_paths"]),
                full_repository=bool(run["full_repository"]),
                supersedes=frozenset(str(v) for v in run["supersedes"]),
            )
            for run in document["runs"]
        ),
    )


def baseline_to_dict(issues: Sequence[CodeSecurityIssue]) -> list[dict[str, Any]]:
    return [
        {
            "issue_id": item.issue_id,
            "weakness_class": item.weakness_class,
            "path": item.path,
            "symbol": item.symbol,
            "producers": list(item.producers),
            "package": item.package,
            "advisory_ids": list(item.advisory_ids),
        }
        for item in (BaselineIssue.from_issue(issue) for issue in issues)
    ]


def baseline_from_dict(entries: Sequence[Mapping[str, Any]]) -> dict[str, BaselineIssue]:
    issues = {}
    for entry in entries:
        issue = BaselineIssue(
            issue_id=str(entry["issue_id"]),
            weakness_class=str(entry["weakness_class"]),
            path=str(entry["path"]),
            symbol=str(entry["symbol"]) if entry.get("symbol") else None,
            producers=tuple(str(p) for p in entry["producers"]),
            package=str(entry["package"]) if entry.get("package") else None,
            advisory_ids=tuple(str(a) for a in entry.get("advisory_ids", [])),
        )
        issues[issue.issue_id] = issue
    return issues


__all__ = [
    "baseline_from_dict",
    "baseline_to_dict",
    "build_receipt",
    "receipt_from_dict",
    "receipt_to_dict",
]
