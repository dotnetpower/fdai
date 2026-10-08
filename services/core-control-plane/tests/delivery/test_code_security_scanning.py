"""Tests for source acquisition, the bubblewrap scanner sandbox, and the scan job."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fdai.delivery.code_security_acquire import GitSourceAcquirer, SourceAcquisitionError
from fdai.delivery.code_security_sandbox import BubblewrapScannerSandbox, sandbox_available
from fdai.delivery.code_security_scan_job import ScanJobConfig, run_scan_job
from fdai.rule_catalog.code_security import load_code_security_catalog
from fdai.rule_catalog.code_security_scanners import (
    ScannerCatalog,
    ScannerSpec,
    load_scanner_catalog,
)
from fdai.rule_catalog.code_security_verifiers import VerifierCatalog

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CATALOG = _REPO_ROOT / "rule-catalog" / "code-security"
_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Example Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Example Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
}
needs_bwrap = pytest.mark.skipif(
    not sandbox_available(), reason="unprivileged bubblewrap unavailable"
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - controlled test command
        ["git", "-C", str(cwd), *args],  # noqa: S607 - git from PATH in tests
        check=True,
        capture_output=True,
        text=True,
        env=_ENV,
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "origin"
    (repo / "src").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    (repo / "src" / "app.py").write_text("import os\nos.system(cmd)\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo, _git(repo, "rev-parse", "HEAD")


def _fake_scanner(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "bin" / "fake-scanner"
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _spec(**overrides: object) -> ScannerSpec:
    values: dict[str, object] = {
        "producer": "Opengrep",
        "argv": ["scan", "{source}"],
        "success_exit_codes": [0],
        "timeout_seconds": 30,
        "max_output_bytes": 100_000,
    }
    values.update(overrides)
    return ScannerSpec.model_validate(values)


def _promoted(verifiers: VerifierCatalog) -> VerifierCatalog:
    """Promote every Python verifier so scan-job tests exercise verification, not the gate."""
    keys = tuple(f"python:{name}" for name in verifiers.python.classes)
    promotion = verifiers.promotion.model_copy(update={"promoted": keys})
    return verifiers.model_copy(update={"promotion": promotion})


def _sarif(driver: str = "Opengrep") -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": driver, "version": "1.0.0"}},
                    "results": [
                        {
                            "ruleId": "fdai.python.os-system",
                            "properties": {"tags": ["CWE-78"]},
                            "message": {"text": "os.system"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "file:///source/src/app.py"},
                                        "region": {"startLine": 2},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def test_acquire_extracts_exact_revision_read_only(tmp_path: Path) -> None:
    repo, revision = _repo(tmp_path)
    source = GitSourceAcquirer(tmp_path / "work").acquire(str(repo), revision)
    assert (source.path / "src" / "app.py").read_text().startswith("import os")
    assert not (source.path / ".git").exists()
    assert not os.stat(source.path / "src" / "app.py").st_mode & stat.S_IWUSR
    assert source.tree_id == _git(repo, "rev-parse", f"{revision}^{{tree}}")
    again = GitSourceAcquirer(tmp_path / "work").acquire(str(repo), revision)
    assert again.path == source.path


@pytest.mark.parametrize(("location", "revision"), [("-oUpload", "a" * 40), ("ok", "main")])
def test_acquire_rejects_bad_input(tmp_path: Path, location: str, revision: str) -> None:
    with pytest.raises(SourceAcquisitionError):
        GitSourceAcquirer(tmp_path).acquire(location, revision)


def test_acquire_rejects_unknown_commit(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    with pytest.raises(SourceAcquisitionError, match="fetch"):
        GitSourceAcquirer(tmp_path / "work").acquire(str(repo), "f" * 40)


def test_sandbox_command_isolates_network_and_mounts_source_read_only(tmp_path: Path) -> None:
    argv = BubblewrapScannerSandbox().command(_spec(), Path("/usr/bin/true"), tmp_path)
    joined = " ".join(argv)
    assert "--unshare-all" in argv and "--clearenv" in argv
    assert f"--ro-bind {tmp_path} /source" in joined
    assert "--bind " not in joined
    assert argv[-2:] == ["scan", "/source"]
    with pytest.raises(ValueError, match="rules"):
        BubblewrapScannerSandbox().command(
            _spec(argv=["scan", "{rules}", "{source}"], mounts=["rules"]),
            Path("/usr/bin/true"),
            tmp_path,
        )


@needs_bwrap
async def test_sandbox_runs_scanner_without_write_or_network(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.py").write_text("x = 1\n")
    script = _fake_scanner(
        tmp_path,
        "touch /source/new 2>/dev/null && echo WROTE\n"
        "cat /sys/class/net/*/address 2>/dev/null | grep -qv 00:00:00:00:00:00 && echo NET\n"
        'echo "$HOME" "$(ls /source)"\n',
    )
    result = await BubblewrapScannerSandbox().run("opengrep", _spec(), script, source)
    output = result.stdout.decode()
    assert result.completed, result.stderr_tail
    assert "WROTE" not in output and "NET" not in output
    assert "/scratch a.py" in output
    assert not (source / "new").exists()


@needs_bwrap
async def test_sandbox_marks_truncation_timeout_and_failure(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    noisy = _fake_scanner(tmp_path, "yes x | head -c 50000\n")
    truncated = await BubblewrapScannerSandbox().run(
        "x", _spec(max_output_bytes=1_000), noisy, source
    )
    assert truncated.truncated and not truncated.completed
    slow = _fake_scanner(tmp_path, "sleep 30\n")
    timed = await BubblewrapScannerSandbox().run("x", _spec(timeout_seconds=10), slow, source)
    assert timed.timed_out and not timed.completed
    failing = _fake_scanner(tmp_path, "exit 3\n")
    failed = await BubblewrapScannerSandbox().run("x", _spec(), failing, source)
    assert failed.exit_code == 3 and not failed.completed


class _Publisher:
    def __init__(self) -> None:
        self.packages: list[dict[str, object]] = []

    async def publish_code_security_drift(self, package: dict[str, object]) -> bool:
        self.packages.append(package)
        return True


@needs_bwrap
async def test_scan_job_end_to_end_with_partial_coverage(tmp_path: Path) -> None:
    repo, revision = _repo(tmp_path)
    scanner = _fake_scanner(tmp_path, f"cat <<'SARIF'\n{_sarif()}\nSARIF\n")
    publisher = _Publisher()
    scanners = load_scanner_catalog(_CATALOG)
    result = await run_scan_job(
        ScanJobConfig(
            repository=str(repo),
            revision=revision,
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={"opengrep": scanner},
            rules_dir=_CATALOG / "rules",
        ),
        catalog=load_code_security_catalog(_CATALOG),
        scanners=scanners,
        acquirer=GitSourceAcquirer(tmp_path / "work"),
        sandbox=BubblewrapScannerSandbox(),
        publisher=publisher,
    )
    (issue,) = result.issues
    assert issue.weakness_class == "command_injection"
    assert issue.fix_site.path == "src/app.py"
    assert result.published and publisher.packages[0]["coverage_complete"] is False
    assert "required scanner gitleaks is not installed" in result.coverage_limits
    (run,) = result.receipt.runs
    assert run.completed is True and run.full_repository is True
    assert ":rules-" in run.rules_version
    assert (result.artifact_dir / "opengrep.sarif").exists()
    complete = await run_scan_job(
        ScanJobConfig(
            repository=str(repo),
            revision=revision,
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={"opengrep": scanner},
            rules_dir=_CATALOG / "rules",
            required_scanners=frozenset({"opengrep"}),
        ),
        catalog=load_code_security_catalog(_CATALOG),
        scanners=ScannerCatalog(
            schema_version=1,
            catalog_id="test-catalog",
            version="1.0.0",
            scanners={"opengrep": scanners.scanners["opengrep"]},
        ),
        acquirer=GitSourceAcquirer(tmp_path / "work"),
        sandbox=BubblewrapScannerSandbox(),
    )
    assert complete.package["coverage_complete"] is True


async def test_scan_job_runs_optional_lens_lane_without_affecting_coverage(tmp_path: Path) -> None:
    from fdai.rule_catalog.code_security_lenses import load_lens_catalog
    from fdai.shared.providers.code_security_lens import (
        LensFinding,
        LensModelIdentity,
        LensRequest,
        LensResponse,
    )

    class _Model:
        def __init__(self, family: str) -> None:
            self.identity = LensModelIdentity(family, family)

        async def review(self, request: LensRequest) -> LensResponse:
            hits = (
                (LensFinding(2, 78, "high", "shell command from input"),)
                if request.lens_id == "command-injection"
                else ()
            )
            return LensResponse(findings=hits, model=self.identity)

    repo, revision = _repo(tmp_path)
    result = await run_scan_job(
        ScanJobConfig(
            repository=str(repo),
            revision=revision,
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={},
            rules_dir=_CATALOG / "rules",
        ),
        catalog=load_code_security_catalog(_CATALOG),
        scanners=load_scanner_catalog(_CATALOG),
        acquirer=GitSourceAcquirer(tmp_path / "work"),
        sandbox=BubblewrapScannerSandbox(),
        lens_catalog=load_lens_catalog(_CATALOG),
        lens_models=[_Model("family-a"), _Model("family-b")],
    )
    (issue,) = result.issues
    assert issue.lanes == ("llm_lens",) and issue.confidence.value == "hypothesis"
    assert result.verifier_results == ()
    assert result.lens_report is not None and result.lens_report.kept == 1
    receipt = json.loads((result.artifact_dir / "receipt.json").read_text())
    assert receipt["lens"]["ran"] is True and receipt["lens"]["kept"] == 1
    assert receipt["lens"]["report"]["rejected_ungrounded"] == 0
    assert receipt["lens"]["hypotheses"] == [
        {
            "path": "src/app.py",
            "line": 2,
            "rule_id": receipt["lens"]["hypotheses"][0]["rule_id"],
            "cwe": [78],
        }
    ]
    assert all("lens" not in limit for limit in result.coverage_limits)


async def test_scan_job_verifier_raises_confirmed_lens_candidate(tmp_path: Path) -> None:
    from fdai.rule_catalog.code_security_lenses import load_lens_catalog
    from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog
    from fdai.shared.providers.code_security_lens import (
        LensFinding,
        LensModelIdentity,
        LensRequest,
        LensResponse,
    )

    class _Model:
        def __init__(self, family: str) -> None:
            self.identity = LensModelIdentity(family, family)

        async def review(self, request: LensRequest) -> LensResponse:
            hits = (
                (LensFinding(5, 78, "high", "shell command from request"),)
                if request.lens_id == "command-injection"
                else ()
            )
            return LensResponse(findings=hits, model=self.identity)

    repo = tmp_path / "origin"
    (repo / "src").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    (repo / "src" / "app.py").write_text(
        "import os\nfrom flask import request\n\ndef run():\n    os.system(request.args['cmd'])\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    revision = _git(repo, "rev-parse", "HEAD")
    catalog = load_code_security_catalog(_CATALOG)
    result = await run_scan_job(
        ScanJobConfig(
            repository=str(repo),
            revision=revision,
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={},
            rules_dir=_CATALOG / "rules",
        ),
        catalog=catalog,
        scanners=load_scanner_catalog(_CATALOG),
        acquirer=GitSourceAcquirer(tmp_path / "work"),
        sandbox=BubblewrapScannerSandbox(),
        lens_catalog=load_lens_catalog(_CATALOG),
        lens_models=[_Model("family-a"), _Model("family-b")],
        verifier_catalog=_promoted(
            load_verifier_catalog(_CATALOG, frozenset(catalog.weakness_classes.classes))
        ),
    )
    (issue,) = result.issues
    assert issue.lanes == ("llm_lens",) and issue.confidence.value == "verified"
    (verdict,) = result.verifier_results
    assert verdict.outcome.value == "verified" and verdict.sink == "os.system"
    receipt = json.loads((result.artifact_dir / "receipt.json").read_text())
    assert receipt["verifiers"]["results"][0]["outcome"] == "verified"


@needs_bwrap
async def test_scan_job_proof_lane_raises_verified_issue_to_proven(tmp_path: Path) -> None:
    from fdai.rule_catalog.code_security_lenses import load_lens_catalog
    from fdai.rule_catalog.code_security_verifiers import load_verifier_catalog
    from fdai.shared.providers.code_security_lens import (
        LensFinding,
        LensModelIdentity,
        LensRequest,
        LensResponse,
    )

    class _Model:
        def __init__(self, family: str) -> None:
            self.identity = LensModelIdentity(family, family)

        async def review(self, request: LensRequest) -> LensResponse:
            hits = (
                (LensFinding(5, 78, "high", "shell command from request"),)
                if request.lens_id == "command-injection"
                else ()
            )
            return LensResponse(findings=hits, model=self.identity)

    repo = tmp_path / "origin"
    (repo / "src").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    (repo / "src" / "app.py").write_text(
        "import os\nfrom flask import request\n\ndef run():\n    os.system(request.args['cmd'])\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    revision = _git(repo, "rev-parse", "HEAD")
    catalog = load_code_security_catalog(_CATALOG)
    result = await run_scan_job(
        ScanJobConfig(
            repository=str(repo),
            revision=revision,
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={},
            rules_dir=_CATALOG / "rules",
        ),
        catalog=catalog,
        scanners=load_scanner_catalog(_CATALOG),
        acquirer=GitSourceAcquirer(tmp_path / "work"),
        sandbox=BubblewrapScannerSandbox(),
        lens_catalog=load_lens_catalog(_CATALOG),
        lens_models=[_Model("family-a"), _Model("family-b")],
        verifier_catalog=_promoted(
            load_verifier_catalog(_CATALOG, frozenset(catalog.weakness_classes.classes))
        ),
        prove_python=Path("/usr/bin/python3").resolve(),
    )
    (issue,) = result.issues
    assert issue.confidence.value == "proven"
    (proof,) = result.proof_results
    assert proof.outcome == "proven" and proof.sink == "os.system"
    receipt = json.loads((result.artifact_dir / "receipt.json").read_text())
    assert receipt["proof"]["enabled"] is True


def test_verifier_evaluation_runs_both_verifiers_on_a_pinned_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    import yaml
    from fdai.delivery.code_security_verifier_eval import evaluate_verifiers

    repo = tmp_path / "origin"
    repo.mkdir()
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _git(repo, "config", "uploadpack.allowAnySHA1InWant", "true")
    (repo / "views.py").write_text(
        "import os\nfrom flask import request\n\ndef run():\n    os.system(request.args['c'])\n"
    )
    (repo / "app.js").write_text("db.query('x' + req.query.a)\nfs.readFile(path)\n")
    (repo / "bench").mkdir()
    (repo / "bench" / "T1.py").write_text((repo / "views.py").read_text())
    (repo / "bench" / "T2.py").write_text("import os\n\ndef run():\n    os.system('ls')\n")
    (repo / "expected.csv").write_text("# test name, category, real vulnerability, cwe\n")
    with (repo / "expected.csv").open("a") as handle:
        handle.write("T1,cmdi,true,78\nT2,cmdi,false,78\nT3,xss,true,79\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    commit = _git(repo, "rev-parse", "HEAD")
    engine = tmp_path / "engine"
    hits = {
        "results": [
            {
                "check_id": "verify.fdai.verify.js.sql-injection",
                "path": "app.js",
                "start": {"line": 1},
            },
            {
                "check_id": "verify.fdai.verify.js.code-injection",
                "path": "app.js",
                "start": {"line": 9},
            },
        ],
        "errors": [],
    }
    # The engine runs in each source tree, so a rule path it can't resolve there yields no hits.
    engine.write_text(
        "#!/bin/sh\n"
        'while [ "$#" -gt 0 ]; do [ "$1" = --config ] && config="$2"; shift; done\n'
        '[ -d "$config" ] || { echo \'{"results": [], "errors": []}\'; exit 0; }\n'
        "cat <<'JSON'\n" + json.dumps(hits) + "\nJSON\n"
    )
    engine.chmod(0o755)
    corpus = tmp_path / "corpus.yaml"
    corpus.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "corpus_id": "test",
                "version": "1.0.0",
                "provenance": "curated",
                "precision_floor": 0.9,
                "min_true_positives": 1,
                "sources": [
                    {
                        "id": "local",
                        "repository": str(repo),
                        "commit": commit,
                        "license": "MIT",
                        "label_source": "test labels",
                        "split": "dev",
                        "locations": [
                            {
                                "path": "views.py",
                                "line": 5,
                                "weakness_class": "command_injection",
                                "verifier": "python",
                                "label": "vulnerable",
                            },
                            {
                                "path": "app.js",
                                "line": 1,
                                "split": "holdout",
                                "weakness_class": "sql_injection",
                                "verifier": "taint",
                                "label": "vulnerable",
                            },
                            {
                                "path": "app.js",
                                "line": 2,
                                "weakness_class": "path_traversal",
                                "verifier": "taint",
                                "label": "safe",
                                "reason": "constant",
                            },
                        ],
                    },
                    {
                        "id": "bench",
                        "repository": str(repo),
                        "commit": commit,
                        "license": "MIT",
                        "label_source": "expected.csv",
                        "expected_results": {
                            "file": "expected.csv",
                            "path_template": "bench/{test}.py",
                            "verifier": "python",
                            "split": "holdout",
                            "categories": {"cmdi": "command_injection"},
                        },
                    },
                ],
            }
        )
    )
    monkeypatch.chdir(_CATALOG.parent)
    receipt = evaluate_verifiers(
        argparse.Namespace(
            corpus=str(corpus),
            work_root=str(tmp_path / "work"),
            engine=str(engine),
            output=str(tmp_path / "receipt.json"),
            catalog_root=_CATALOG.name,
        )
    )
    verifiers: list[dict[str, Any]] = receipt["verifiers"]  # type: ignore[assignment]
    by_key = {item["key"]: item for item in verifiers}
    command = by_key["python:command_injection"]
    assert command["dev"]["true_positives"] == 1
    assert command["holdout"]["true_positives"] == 1
    assert command["holdout"]["true_negatives"] == 1
    assert command["promoted"] is True
    assert by_key["fdai.verify.js.sql-injection"]["holdout"]["true_positives"] == 1
    assert by_key["fdai.verify.js.sql-injection"]["promoted"] is False
    assert by_key["fdai.verify.js.path-traversal"]["dev"]["true_negatives"] == 1
    assert receipt["labels"] == {"dev": 2, "holdout": 3}
    assert receipt["unlabeled_verified"] == [
        {"source": "local", "rule": "fdai.verify.js.code-injection", "path": "app.js", "line": 9}
    ]
    assert json.loads((tmp_path / "receipt.json").read_text())["promoted"] == receipt["promoted"]


@needs_bwrap
async def test_scan_job_binds_receipt_to_the_catalog_producer_not_the_tool_name(
    tmp_path: Path,
) -> None:
    repo, revision = _repo(tmp_path)
    scanner = _fake_scanner(tmp_path, f"cat <<'SARIF'\n{_sarif('Opengrep OSS')}\nSARIF\n")
    scanners = load_scanner_catalog(_CATALOG)
    result = await run_scan_job(
        ScanJobConfig(
            repository=str(repo),
            revision=revision,
            repository_alias="example-service",
            work_root=tmp_path / "work",
            executables={"opengrep": scanner},
            rules_dir=_CATALOG / "rules",
            required_scanners=frozenset({"opengrep"}),
        ),
        catalog=load_code_security_catalog(_CATALOG),
        scanners=scanners,
        acquirer=GitSourceAcquirer(tmp_path / "work"),
        sandbox=BubblewrapScannerSandbox(),
    )
    (run,) = result.receipt.runs
    assert run.producer == "Opengrep"
    assert run.rules_version.startswith("opengrep:1.0.0:rules-")
    assert run.full_repository is True
    (issue,) = result.issues
    assert issue.producers == ("Opengrep",)


def test_scan_runner_image_pins_every_tool_and_binds_every_scanner() -> None:
    import re

    docker = _REPO_ROOT / "services" / "core-control-plane" / "docker"
    dockerfile = (docker / "code-security-scanner.Dockerfile").read_text(encoding="utf-8")
    entrypoint = (docker / "code-security-scanner-entrypoint.sh").read_text(encoding="utf-8")
    for tool in ("OPENGREP", "GITLEAKS", "OSV_SCANNER", "TRIVY"):
        assert re.search(rf"ARG {tool}_SHA256=[0-9a-f]{{64}}\n", dockerfile), tool
        assert f'"${{{tool}_SHA256}}' in dockerfile, f"{tool} download is not verified"
    assert re.findall(r"library/python@sha256:[0-9a-f]{64}", dockerfile)
    bound = set(re.findall(r'--scanner-bin "([a-z-]+)=', entrypoint))
    assert bound == set(load_scanner_catalog(_CATALOG).scanners)
    assert re.search(r"ARG DOTNET_SDK_SHA512=[0-9a-f]{128}\n", dockerfile)
    assert '"${DOTNET_SDK_SHA512}  dotnet.tar.gz" | sha512sum -c -' in dockerfile
    stages = re.findall(r"^FROM \S+ AS ([a-z]+)$", dockerfile, flags=re.MULTILINE)
    assert stages[-1] == "runtime" and "prover" in stages
    prover = dockerfile.split(" AS prover\n", 1)[1].split("\nFROM ", 1)[0]
    for toolchain in ("nodejs", "gcc", "openjdk-21-jdk-headless", "/usr/lib/dotnet"):
        assert toolchain in prover, toolchain
    for flag in ("node:node", "gcc:cc", "java:java", "dotnet:dotnet"):
        assert flag in entrypoint, flag
