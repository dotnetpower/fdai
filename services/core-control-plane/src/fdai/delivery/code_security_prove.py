"""Opt-in proof lane (``code-build-prove``): reproduce verified findings in a sandbox.

Proof imports and calls repository code, so it runs only when an operator enables it for a
repository, and only for issues a deterministic verifier already confirmed. The harness and its
target list are staged in an owner-only directory mounted read-only; the source is read-only; the
sandbox has no network, no credentials, a cleared environment, and CPU, memory, file-size, and
time limits. Every sink is replaced by a recording hook, so a successful proof never performs
the real command, evaluation, deserialization, query, or file access.

Each supported language has its own harness payload under ``rule-catalog/code-security/prove/``
and runtime: Python (``fdai_prove.py``), JavaScript on Node.js (``fdai_prove.js``), and native C
and C++ (``fdai_prove_native.py``). A target's language comes from its fix-site extension, and a
language runs only when the operator supplies its runtime.

Native memory-safety issues have no deterministic verifier, so they are eligible when a
deterministic or external producer reported them (never the LLM lens alone). Their proof is a
sanitizer report whose first frame in the target file is the fix-site line. The native harness runs
on the sandbox's Python with the compiler path as its last argument, and without the sandbox
address-space limit, because AddressSanitizer reserves terabytes of shadow address space; the
harness bounds the compiler's address space and every run's resident memory instead.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from fdai.core.security.code_findings.models import CodeSecurityIssue, Lane
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
_PROVE_ROOT = repo_asset_root() / "rule-catalog" / "code-security" / "prove"
_OUTCOMES = frozenset({"proven", "not_proven"})


@dataclass(frozen=True, slots=True)
class ProofLanguage:
    """One harness payload (a sandbox file FDAI never imports) and the files it can prove."""

    name: str
    harness: str
    suffixes: tuple[str, ...]
    classes: frozenset[str]
    runtime_args: tuple[str, ...] = ()
    compiled: bool = False


PROOF_LANGUAGES: Mapping[str, ProofLanguage] = {
    "python": ProofLanguage("python", "fdai_prove.py", (".py",), PROVABLE_CLASSES, ("-I",)),
    "javascript": ProofLanguage(
        "javascript",
        "fdai_prove.js",
        (".js", ".cjs"),
        frozenset({"command_injection", "code_injection", "sql_injection", "path_traversal"}),
    ),
    "native": ProofLanguage(
        "native",
        "fdai_prove_native.py",
        (".c", ".cc", ".cpp", ".cxx"),
        frozenset({"memory_safety"}),
        ("-I",),
        compiled=True,
    ),
}
_REPORTED_LANES = frozenset({Lane.DETERMINISTIC, Lane.EXTERNAL})


def proof_language(path: str) -> ProofLanguage | None:
    """Return the proof language for a fix-site path, or ``None`` when none applies."""
    return next((lang for lang in PROOF_LANGUAGES.values() if path.endswith(lang.suffixes)), None)


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
    issues: Sequence[CodeSecurityIssue],
    verifier_results: Sequence[VerifierResult],
    languages: Collection[str] = ("python",),
) -> list[dict[str, object]]:
    """Return proof targets: verified issues in a provable class of an enabled language."""
    verified = {
        result.issue_id for result in verifier_results if result.outcome is VerifierOutcome.VERIFIED
    }
    targets: list[dict[str, object]] = []
    for issue in issues:
        language = proof_language(issue.fix_site.path)
        eligible = (
            bool(_REPORTED_LANES & set(issue.lanes))
            if language is not None and language.compiled
            else issue.issue_id in verified
        )
        if (
            eligible
            and language is not None
            and language.name in languages
            and issue.weakness_class in language.classes
            and issue.fix_site.start_line
        ):
            targets.append(
                {
                    "issue_id": issue.issue_id,
                    "path": issue.fix_site.path,
                    "line": issue.fix_site.start_line,
                    "weakness_class": issue.weakness_class,
                    "language": language.name,
                }
            )
    return targets


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


async def _prove_language(
    source: Path,
    language: ProofLanguage,
    targets: Sequence[Mapping[str, object]],
    *,
    sandbox: BubblewrapScannerSandbox,
    runtime: Path,
    interpreter: Path | None,
    timeout_seconds: int,
) -> list[ProofResult]:
    stage = Path(tempfile.mkdtemp(prefix="fdai-prove-"))
    try:
        os.chmod(stage, 0o700)
        shutil.copyfile(_PROVE_ROOT / language.harness, stage / language.harness)
        (stage / "targets.json").write_text(json.dumps(list(targets)), encoding="utf-8")
        spec = ScannerSpec(
            producer=f"fdai-prove-{language.name}",
            argv=(
                *language.runtime_args,
                f"{{rules}}/{language.harness}",
                "{source}",
                "{rules}/targets.json",
                *((str(runtime),) if language.compiled else ()),
            ),
            mounts=("rules",),
            success_exit_codes=(0,),
            timeout_seconds=timeout_seconds,
            max_output_bytes=1_000_000,
        )
        if language.compiled and interpreter is None:
            return [
                ProofResult(str(t["issue_id"]), "not_proven", "no_interpreter") for t in targets
            ]
        run = await sandbox.run(
            f"fdai-prove-{language.name}",
            spec,
            interpreter if language.compiled and interpreter is not None else runtime,
            source,
            rules=stage,
            limit_address_space=not language.compiled,
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    if not run.completed:
        reason = "timed_out" if run.timed_out else "truncated" if run.truncated else "failed"
        return [ProofResult(str(t["issue_id"]), "not_proven", reason) for t in targets]
    return parse_proof_output(run.stdout, targets)


async def prove_issues(
    source: Path,
    issues: Sequence[CodeSecurityIssue],
    verifier_results: Sequence[VerifierResult],
    *,
    sandbox: BubblewrapScannerSandbox,
    python: Path | None = None,
    runtimes: Mapping[str, Path] | None = None,
    timeout_seconds: int = 300,
) -> tuple[ProofResult, ...]:
    """Run each enabled language's harness in the sandbox and return one result per target.

    ``runtimes`` maps a proof language to its interpreter, or to its compiler for native code;
    ``python`` is shorthand for the Python runtime, which also runs the native harness. Languages
    without a runtime are not proven.
    """
    available = dict(runtimes or {})
    if python is not None:
        available.setdefault("python", python)
    targets = proof_targets(issues, verifier_results, tuple(available))
    results: list[ProofResult] = []
    for name in sorted({str(target["language"]) for target in targets}):
        mine = [target for target in targets if target["language"] == name]
        results.extend(
            await _prove_language(
                source,
                PROOF_LANGUAGES[name],
                mine,
                sandbox=sandbox,
                runtime=available[name],
                interpreter=available.get("python"),
                timeout_seconds=timeout_seconds,
            )
        )
    return tuple(sorted(results, key=lambda item: item.issue_id))


def proven_confidence(results: Sequence[ProofResult]) -> Mapping[str, Confidence]:
    return {item.issue_id: Confidence.PROVEN for item in results if item.outcome == "proven"}


__all__ = [
    "PROOF_LANGUAGES",
    "PROVABLE_CLASSES",
    "ProofLanguage",
    "ProofResult",
    "parse_proof_output",
    "proof_language",
    "proof_targets",
    "prove_issues",
    "proven_confidence",
]
