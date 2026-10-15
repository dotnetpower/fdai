"""Tests for compiler-backed C# graph-flow analysis."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fdai.core.security.code_findings.analysis_evaluation import evaluate_csharp_analysis
from fdai.core.security.code_findings.csharp_analysis import (
    CSharpCompilerConfig,
    analyze_csharp_repository,
)
from fdai.rule_catalog.code_security_analysis import load_analysis_rules
from fdai.rule_catalog.code_security_analysis_evaluation import load_analysis_evaluation_corpus

from ._support import CATALOG_ROOT, REPO_ROOT, REVISION

DIGEST = "sha256:" + "b" * 64


@pytest.fixture(scope="module")
def compiler(tmp_path_factory: pytest.TempPathFactory) -> CSharpCompilerConfig:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("the .NET SDK is required for compiler-backed C# analysis")
    output = tmp_path_factory.mktemp("csharp-frontend")
    subprocess.run(  # noqa: S603 - exact local SDK and trusted project
        [
            dotnet,
            "build",
            str(
                REPO_ROOT
                / "tools"
                / "code-security-csharp-frontend"
                / "Fdai.CSharp.Frontend.csproj"
            ),
            "--configuration",
            "Release",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": str(Path(dotnet).parent), "DOTNET_CLI_TELEMETRY_OPTOUT": "1"},
        timeout=60,
    )
    return CSharpCompilerConfig(
        dotnet=Path(dotnet),
        assembly=output / "Fdai.CSharp.Frontend.dll",
    )


def _rule():  # type: ignore[no-untyped-def]
    return next(
        item
        for item in load_analysis_rules(CATALOG_ROOT)
        if item.rule_id == "fdai.csharp.sql-injection"
    )


def test_csharp_compiler_evaluation_is_disaggregated_and_shadow_only(
    tmp_path: Path, compiler: CSharpCompilerConfig
) -> None:
    corpus = load_analysis_evaluation_corpus(CATALOG_ROOT, "csharp-compiler-sql-injection")

    receipt = evaluate_csharp_analysis(corpus, _rule(), tmp_path, compiler)

    assert receipt.dev.precision == receipt.dev.recall == 1.0
    assert receipt.holdout.precision == receipt.holdout.recall == 1.0
    assert receipt.dev.unsupported == receipt.holdout.unsupported == 0
    assert receipt.multi_file_path_recall == 1.0
    assert receipt.meets_initial_thresholds is True
    assert receipt.promotion_eligible is False
    recorded = json.loads(
        (CATALOG_ROOT / "evaluation" / "csharp-compiler-analysis-1.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    recorded.pop("resources")
    assert recorded == receipt.stable_dict()


def test_csharp_compiler_diagnostics_are_explicit_coverage(
    tmp_path: Path, compiler: CSharpCompilerConfig
) -> None:
    (tmp_path / "Broken.cs").write_text(
        "class Broken { object Run() { return Missing.Call(); } }",
        encoding="utf-8",
    )

    result = analyze_csharp_repository(
        tmp_path,
        revision=REVISION,
        build_context_digest=DIGEST,
        framework_model_digest=_rule().digest(),
        rule=_rule(),
        config=compiler,
    )

    assert result is not None
    assert any(
        item.startswith("csharp.compiler-attribution-errors:")
        for item in result.graph.coverage_limits
    )


def test_csharp_source_symlink_is_rejected(tmp_path: Path, compiler: CSharpCompilerConfig) -> None:
    outside = tmp_path.parent / "Outside.cs"
    outside.write_text("class Outside {}", encoding="utf-8")
    (tmp_path / "Linked.cs").symlink_to(outside)

    with pytest.raises(ValueError, match="escapes"):
        analyze_csharp_repository(
            tmp_path,
            revision=REVISION,
            build_context_digest=DIGEST,
            framework_model_digest=_rule().digest(),
            rule=_rule(),
            config=compiler,
        )


def test_csharp_frontend_rejects_unordered_path_contract(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "App.cs").write_text("class App {}", encoding="utf-8")
    assembly = tmp_path / "frontend.dll"
    assembly.write_bytes(b"trusted-placeholder")
    frontend = tmp_path / "dotnet"
    frontend.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({"
        "'schema_version':'1.0.0','compiler_version':'5.0.0','methods':[],"
        "'error_count':0,'coverage_limits':[],"
        "'paths':[[{'role':'sink','path':'App.cs','line':1,'name':'sink','context':[]},"
        "{'role':'source','path':'App.cs','line':1,'name':'source','context':[]}]]}))\n",
        encoding="utf-8",
    )
    frontend.chmod(0o755)

    with pytest.raises(ValueError, match="violates its contract"):
        analyze_csharp_repository(
            source,
            revision=REVISION,
            build_context_digest=DIGEST,
            framework_model_digest=_rule().digest(),
            rule=_rule(),
            config=CSharpCompilerConfig(dotnet=frontend, assembly=assembly),
        )
