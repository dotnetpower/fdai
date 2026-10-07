"""Opt-in proof lane (``code-build-prove``): reproduce verified Python findings in a sandbox.

Proof imports and calls repository code, so it runs only when an operator enables it for a
repository, and only for issues a deterministic verifier already confirmed. The harness and its
target list are staged in an owner-only directory mounted read-only; the source is read-only; the
sandbox has no network, no credentials, a cleared environment, and CPU, memory, file-size, and
time limits. Every sink is replaced by a recording hook, so a successful proof never performs
the real command, evaluation, deserialization, query, or file access.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai.core.security.code_findings.models import CodeSecurityIssue
from fdai.core.security.code_findings.verifier import VerifierOutcome, VerifierResult
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox
from fdai.delivery.repo_assets import repo_asset_root
from fdai.rule_catalog.code_security import Confidence
from fdai.rule_catalog.code_security_scanners import ScannerSpec

PROVABLE_CLASSES = frozenset(
    {
        "command_injection",
        "code_injection",
        "unsafe_deserialization",
        "sql_injection",
        "path_traversal",
    }
)
_HARNESS = repo_asset_root() / "rule-catalog" / "code-security" / "prove" / "fdai_prove.py"
"""A sandbox payload, not an FDAI module: it is copied into the sandbox and never imported."""
_OUTCOMES = frozenset({"proven", "not_proven"})


@dataclass(frozen=True, slots=True)
class ProofResult:
    issue_id: str
    outcome: str
    reason: str
    sink: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "issue_id": self.issue_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "sink": self.sink,
        }


def proof_targets(
    issues: Sequence[CodeSecurityIssue], verifier_results: Sequence[VerifierResult]
) -> list[dict[str, object]]:
    """Return proof targets: verified Python issues in provable classes."""
    verified = {
        result.issue_id for result in verifier_results if result.outcome is VerifierOutcome.VERIFIED
    }
    return [
        {
            "issue_id": issue.issue_id,
            "path": issue.fix_site.path,
            "line": issue.fix_site.start_line,
            "weakness_class": issue.weakness_class,
        }
        for issue in issues
        if issue.issue_id in verified
        and issue.weakness_class in PROVABLE_CLASSES
        and issue.fix_site.path.endswith(".py")
        and issue.fix_site.start_line
    ]


def parse_proof_output(stdout: bytes, targets: Sequence[Mapping[str, object]]) -> list[ProofResult]:
    """Parse harness JSON lines; targets without a well-formed line stay unproven."""
    expected = {str(target["issue_id"]) for target in targets}
    seen: dict[str, ProofResult] = {}
    for line in stdout.decode("utf-8", "replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        issue_id, outcome = item.get("issue_id"), item.get("outcome")
        if issue_id not in expected or outcome not in _OUTCOMES or issue_id in seen:
            continue
        sink = item.get("sink")
        seen[str(issue_id)] = ProofResult(
            str(issue_id),
            str(outcome),
            str(item.get("reason", ""))[:64],
            str(sink)[:128] if isinstance(sink, str) else None,
        )
    return [
        seen.get(issue_id, ProofResult(issue_id, "not_proven", "no_result"))
        for issue_id in sorted(expected)
    ]


async def prove_issues(
    source: Path,
    issues: Sequence[CodeSecurityIssue],
    verifier_results: Sequence[VerifierResult],
    *,
    sandbox: BubblewrapScannerSandbox,
    python: Path,
    timeout_seconds: int = 300,
) -> tuple[ProofResult, ...]:
    """Run the harness in the sandbox for every proof target and return one result each."""
    targets = proof_targets(issues, verifier_results)
    if not targets:
        return ()
    stage = Path(tempfile.mkdtemp(prefix="fdai-prove-"))
    try:
        os.chmod(stage, 0o700)
        shutil.copyfile(_HARNESS, stage / "fdai_prove.py")
        (stage / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
        spec = ScannerSpec(
            producer="fdai-prove",
            argv=("-I", "{rules}/fdai_prove.py", "{source}", "{rules}/targets.json"),
            mounts=("rules",),
            success_exit_codes=(0,),
            timeout_seconds=timeout_seconds,
            max_output_bytes=1_000_000,
        )
        run = await sandbox.run("fdai-prove", spec, python, source, rules=stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if not run.completed:
        reason = "timed_out" if run.timed_out else "truncated" if run.truncated else "failed"
        return tuple(ProofResult(str(t["issue_id"]), "not_proven", reason) for t in targets)
    return tuple(parse_proof_output(run.stdout, targets))


def proven_confidence(results: Sequence[ProofResult]) -> Mapping[str, Confidence]:
    return {item.issue_id: Confidence.PROVEN for item in results if item.outcome == "proven"}


__all__ = [
    "PROVABLE_CLASSES",
    "ProofResult",
    "parse_proof_output",
    "proof_targets",
    "prove_issues",
    "proven_confidence",
]
