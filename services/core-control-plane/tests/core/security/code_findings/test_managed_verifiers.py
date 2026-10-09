"""Managed-language shadow boundaries and frozen evaluation evidence."""

from __future__ import annotations

import hashlib
import json

import pytest
from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.models import Lane
from fdai.core.security.code_findings.sarif import SarifIngestContext, ingest_sarif
from fdai.core.security.code_findings.verifier import (
    VerifierOutcome,
    taint_rule_verifications,
    verified_confidence,
)
from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog

from ._support import CATALOG_ROOT, REVISION, catalog, result, sarif


@pytest.mark.parametrize(
    ("rule", "path", "cwe"),
    [
        ("fdai.verify.java.path-traversal", "Upload.java", 22),
        ("fdai.verify.csharp.command-injection", "Shell.cs", 78),
        ("fdai.verify.csharp.sql-injection", "Orders.cs", 89),
        ("fdai.verify.csharp.path-traversal", "Download.cs", 22),
    ],
)
def test_managed_verifier_improvements_do_not_bypass_shadow_gate(
    rule: str, path: str, cwe: int
) -> None:
    occurrences = ingest_sarif(
        sarif("Opengrep", [result(rule, path, 25, cwe=cwe)]),
        SarifIngestContext(lane=Lane.DETERMINISTIC, revision=REVISION),
    ).occurrences
    shipped = load_verifier_catalog(CATALOG_ROOT, frozenset(catalog().weakness_classes.classes))
    (issue,) = build_issues(occurrences, catalog(), AnalysisContext(revision=REVISION))
    (verdict,) = taint_rule_verifications((issue,), occurrences, shipped)
    assert verdict.outcome is VerifierOutcome.NOT_VERIFIED
    assert verdict.reason == "verifier_in_shadow"
    assert verified_confidence((verdict,)) == {}


def test_managed_verifier_receipt_binds_frozen_rules_and_promotion() -> None:
    receipt = json.loads((CATALOG_ROOT / "evaluation" / "managed-verifiers-1.5.0.json").read_text())
    shipped = load_verifier_catalog(CATALOG_ROOT, frozenset(catalog().weakness_classes.classes))
    assert receipt["candidate_verifier_version"] == shipped.version
    assert set(receipt["promoted"]) == set(shipped.promotion.promoted)
    rule_files = sorted((CATALOG_ROOT / "rules" / "verify").glob("*.yaml"))
    digest = hashlib.sha256(
        b"".join(path.name.encode() + b"\0" + path.read_bytes() for path in rule_files)
    ).hexdigest()
    assert receipt["frozen_rules_sha256"] == digest
    assert (
        receipt["corpus_sha256"]
        == hashlib.sha256(
            (CATALOG_ROOT / "evaluation" / "verifier-corpus.yaml").read_bytes()
        ).hexdigest()
    )
    assert receipt["labels"] == {"dev": 710, "holdout": 681}
    assert receipt["engine"]["network"] == "none"
    assert all(
        observation["engine_exit_code"] == 0 and observation["all_labeled_files_observed"]
        for observation in receipt["observations"]
    )
