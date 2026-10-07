"""Tests for root-cause canonicalization: one issue, one severity."""

from __future__ import annotations

import pytest
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import InstanceFacts, Lane, Occurrence
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.rule_catalog.code_security import (
    AttackVector,
    Confidence,
    Exposure,
    Impact,
    Priority,
    PrivilegesRequired,
    UserInteraction,
)

from ._support import REVISION, catalog, result, sarif


def _occ(
    producer: str, items: list[dict[str, object]], lane: Lane = Lane.EXTERNAL
) -> list[Occurrence]:
    return list(
        ingest_sarif(
            sarif(producer, items), SarifIngestContext(lane=lane, revision=REVISION)
        ).occurrences
    )


def _issues(occurrences: list[Occurrence], **kwargs: object):  # type: ignore[no-untyped-def]
    return build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION, **kwargs))  # type: ignore[arg-type]


def test_same_root_cause_from_three_lanes_is_one_issue_with_one_severity() -> None:
    occurrences = (
        _occ("MDASH", [result("mdash-sqli", "src/db.py", 42, cwe=89, level="error")])
        + _occ(
            "Opengrep",
            [result("python.sqli", "src/db.py", 42, cwe=89, level="warning")],
            Lane.DETERMINISTIC,
        )
        + _occ(
            "fdai-lens",
            [result("lens.sqli", "src/db.py", 42, cwe=943, level="note")],
            Lane.LLM_LENS,
        )
    )
    (issue,) = _issues(occurrences)
    assert issue.weakness_class == "sql_injection"
    assert issue.confidence is Confidence.CORROBORATED
    assert issue.producers == ("MDASH", "Opengrep", "fdai-lens")
    assert len(issue.source_severities) == 3
    assert issue.severity.label in ("undetermined", "high", "critical", "medium", "low")


def test_distinct_sources_into_one_sink_are_instances_of_one_issue() -> None:
    occurrences = _occ(
        "CodeQL",
        [
            result("sqli", "src/db.py", 42, cwe=89, flow=[("src/api_a.py", 5), ("src/db.py", 42)]),
            result("sqli", "src/db.py", 42, cwe=89, flow=[("src/api_b.py", 9), ("src/db.py", 42)]),
        ],
    )
    (issue,) = _issues(occurrences)
    assert len(issue.instances) == 2
    assert issue.governing_instance_id in {item.instance_id for item in issue.instances}


def test_different_weakness_classes_or_sinks_are_not_merged() -> None:
    occurrences = _occ(
        "CodeQL",
        [
            result("sqli", "src/db.py", 42, cwe=89),
            result("xss", "src/db.py", 42, cwe=79),
            result("sqli", "src/db.py", 50, cwe=89),
        ],
    )
    assert len(_issues(occurrences)) == 3


def test_unlisted_cwe_never_merges_across_producers() -> None:
    occurrences = _occ("ToolA", [result("a.rule", "src/x.py", 3, cwe=20)]) + _occ(
        "ToolB", [result("b.rule", "src/x.py", 3, cwe=20)]
    )
    issues = _issues(occurrences)
    assert len(issues) == 2
    assert all(issue.weakness_class.startswith("unclassified:") for issue in issues)


def test_dependency_aliases_across_layers_collapse_to_one_issue() -> None:
    lock = result(
        "CVE-2024-11111",
        "app/package-lock.json",
        1,
        properties={"packageName": "libx", "security-severity": "8.1"},
    )
    image = result(
        "GHSA-cfgh-jmpq-rvwx",
        "image/usr/lib/node_modules/libx/package.json",
        1,
        properties={"packageName": "libx", "security-severity": "8.1", "tags": ["CVE-2024-11111"]},
    )
    (issue,) = _issues(_occ("Trivy", [lock]) + _occ("GHAS", [image]))
    assert issue.weakness_class == "vulnerable_dependency"
    assert issue.advisory_ids == ("CVE-2024-11111", "GHSA-cfgh-jmpq-rvwx")
    assert len(issue.layers) == 2
    assert issue.severity.label == "high"


def test_kev_changes_priority_but_never_severity() -> None:
    lock = result(
        "CVE-2024-22222",
        "package-lock.json",
        1,
        properties={"packageName": "liby", "security-severity": "7.5"},
    )
    base = _issues(_occ("Trivy", [lock]))[0]
    exploited = _issues(_occ("Trivy", [lock]), known_exploited=frozenset({"CVE-2024-22222"}))[0]
    assert base.severity == exploited.severity
    assert exploited.known_exploited is True
    assert exploited.priority.priority is Priority.P0
    assert base.priority.priority is not Priority.P0


def test_exposure_changes_priority_but_never_severity() -> None:
    occurrences = _occ("CodeQL", [result("cmdi", "src/run.py", 7, cwe=78)])
    exposed = _issues(occurrences, exposure=Exposure.EXPOSED)[0]
    parked = _issues(occurrences, exposure=Exposure.NOT_DEPLOYED)[0]
    assert exposed.severity == parked.severity
    assert parked.priority.priority is Priority.P2


def test_verified_facts_and_verification_determine_label_and_confidence() -> None:
    occurrences = _occ("CodeQL", [result("cmdi", "src/run.py", 7, cwe=78)])
    first = _issues(occurrences)[0]
    facts = InstanceFacts(
        impact=Impact.CODE_EXECUTION,
        attack_vector=AttackVector.NETWORK,
        privileges_required=PrivilegesRequired.NONE,
        user_interaction=UserInteraction.NONE,
        evidence_refs=("verifier:entrypoint/1",),
    )
    verified = _issues(
        occurrences,
        exposure=Exposure.EXPOSED,
        instance_facts={first.instances[0].instance_id: facts},
        verifications={first.issue_id: Confidence.VERIFIED},
    )[0]
    assert verified.issue_id == first.issue_id
    assert verified.severity.label == "critical"
    assert verified.confidence is Confidence.VERIFIED
    assert verified.priority.priority is Priority.P0


def test_llm_only_findings_are_hypotheses() -> None:
    (issue,) = _issues(
        _occ("fdai-lens", [result("lens.idor", "src/views.py", 12, cwe=639)], Lane.LLM_LENS)
    )
    assert issue.confidence is Confidence.HYPOTHESIS


def test_mixed_revisions_are_rejected() -> None:
    occurrences = list(
        ingest_sarif(
            sarif("tool", [result("r", "src/a.py", 1, cwe=89)]),
            SarifIngestContext(lane=Lane.EXTERNAL, revision="b" * 40),
        ).occurrences
    )
    with pytest.raises(ValueError, match="revision"):
        _issues(occurrences)


def test_issue_ids_are_stable_across_runs_and_producers() -> None:
    first = _issues(_occ("ToolA", [result("x", "src/db.py", 42, cwe=89)]))[0]
    second = _issues(_occ("ToolB", [result("y", "src/db.py", 42, cwe=564)]))[0]
    assert first.issue_id == second.issue_id


def test_misconfiguration_and_secret_tags_classify_without_cwe() -> None:
    occurrences = _occ(
        "Trivy",
        [
            result("DS-0002", "Dockerfile", 1, properties={"tags": ["misconfiguration", "HIGH"]}),
            result("generic-api-key", "src/config.py", 3, properties={"tags": ["secret"]}),
        ],
    )
    classes = sorted(issue.weakness_class for issue in _issues(occurrences))
    assert classes == ["hardcoded_secret", "insecure_configuration"]
