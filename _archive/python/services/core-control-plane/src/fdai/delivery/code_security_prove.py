"""Opt-in proof lane (``code-build-prove``): reproduce verified findings in a sandbox.

Proof imports and calls repository code, so it runs only when an operator enables it for a
repository, and only for issues a deterministic verifier already confirmed. The harness and its
target list are staged in an owner-only directory mounted read-only; the source is read-only; the
sandbox has no network, no credentials, a cleared environment, and CPU, memory, file-size, and
time limits. Every sink is replaced by a recording hook, so a successful proof never performs
the real command, evaluation, deserialization, query, or file access.

Each supported language has its own harness payload under ``rule-catalog/code-security/prove/``
and runtime: Python (``fdai_prove.py``), JavaScript on Node.js (``fdai_prove.js``), native C
and C++ (``fdai_prove_native.py``), and Java and C# (``fdai_prove_managed.py``). A target's
language comes from its fix-site extension, and a language runs only when the operator supplies
its runtime.

Java and C# have no module loader to hook, so their harness rewrites a copy of the fix-site file
without moving any line: every sink argument passes through a recording hook that returns an
inert value, and the copy is compiled alone with the supplied ``java`` (and the ``javac`` beside
it) or ``dotnet`` SDK. Like the native harness, it runs on the sandbox's Python with the toolchain
path as its last argument. A driven toolchain must resolve inside the sandbox's read-only system
mounts, and a file that needs project dependencies stays unproven.

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
_MANAGED_CLASSES = frozenset({"command_injection", "sql_injection", "path_traversal"})
# Read-only system mounts of the scanner sandbox; a driven toolchain must resolve inside them.
_SANDBOX_SYSTEM_ROOTS = (Path("/usr"), Path("/bin"), Path("/lib"), Path("/lib64"))


@dataclass(frozen=True, slots=True)
class ProofLanguage:
    """One harness payload (a sandbox file FDAI never imports) and the files it can prove."""

    name: str
    harness: str
    suffixes: tuple[str, ...]
    classes: frozenset[str]
    runtime_args: tuple[str, ...] = ()
    compiled: bool = False
    driven: bool = False


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
        driven=True,
    ),
    "java": ProofLanguage(
        "java",
        "fdai_prove_managed.py",
        (".java",),
        _MANAGED_CLASSES,
        ("-I",),
        driven=True,
    ),
    "csharp": ProofLanguage(
        "csharp",
        "fdai_prove_managed.py",
        (".cs",),
        _MANAGED_CLASSES,
        ("-I",),
        driven=True,
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
    conflicts: set[str] = set()
    for line in stdout.decode("utf-8", "replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        issue_id, outcome = item.get("issue_id"), item.get("outcome")
        if not isinstance(issue_id, str) or not isinstance(outcome, str):
            continue
        if issue_id not in expected or outcome not in _OUTCOMES:
            continue
        sink = item.get("sink")
        result = ProofResult(
            issue_id,
            outcome,
            str(item.get("reason", ""))[:64],
            str(sink)[:128] if isinstance(sink, str) else None,
        )
        prior = seen.get(issue_id)
        if prior is not None and prior != result:
            conflicts.add(issue_id)
        else:
            seen[issue_id] = result
    return [
        ProofResult(issue_id, "not_proven", "conflicting_results")
        if issue_id in conflicts
        else seen.get(issue_id, ProofResult(issue_id, "not_proven", "no_result"))
        for issue_id in sorted(expected)
    ]


def _toolchain_config(java: Path) -> tuple[Path, ...]:
    """Return the ``/etc/<name>`` directories the JDK's ``conf`` links resolve into.

    Distribution JDKs link ``conf/security/java.security`` and its siblings into ``/etc``; the
    compiler cannot start without them, and the sandbox exposes nothing else of ``/etc``.
    """
    conf = java.parent.parent / "conf"
    found: set[Path] = set()
    for path in conf.rglob("*") if conf.is_dir() else ():
        if path.is_symlink():
            target = path.resolve()
            if target.is_relative_to("/etc") and len(target.parts) > 2:
                found.add(Path("/etc", target.parts[2]))
    return tuple(sorted(found))


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
    if language.driven:
        runtime = runtime.resolve()
        if not any(runtime.is_relative_to(root) for root in _SANDBOX_SYSTEM_ROOTS):
            return [
                ProofResult(str(t["issue_id"]), "not_proven", "runtime_unavailable")
                for t in targets
            ]
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
                *((str(runtime),) if language.driven else ()),
            ),
            mounts=("rules",),
            success_exit_codes=(0,),
            timeout_seconds=timeout_seconds,
            max_output_bytes=1_000_000,
        )
        if language.driven and interpreter is None:
            return [
                ProofResult(str(t["issue_id"]), "not_proven", "no_interpreter") for t in targets
            ]
        run = await sandbox.run(
            f"fdai-prove-{language.name}",
            spec,
            interpreter if language.driven and interpreter is not None else runtime,
            source,
            rules=stage,
            limit_address_space=not language.compiled,
            system_config=_toolchain_config(runtime) if language.name == "java" else (),
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

    ``runtimes`` maps a proof language to its interpreter, to its compiler for native code, or to
    ``java`` or ``dotnet`` for Java and C#; ``python`` is shorthand for the Python runtime, which
    also runs the native, Java, and C# harnesses. Languages without a runtime are not proven.
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
