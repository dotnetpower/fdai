"""Tests for the scanner catalog and the FDAI-authored rule pack structure."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml
from fdai.rule_catalog.code_security import CodeSecurityCatalogError
from fdai.rule_catalog.code_security_scanners import load_scanner_catalog, resolve_argv

from ._support import CATALOG_ROOT, catalog

_RULES = CATALOG_ROOT / "rules"
_FIXTURE_SUFFIX = {"python": ".py", "javascript": ".js", "java": ".java", "go": ".go"}


def test_shipped_scanner_catalog_loads_and_resolves() -> None:
    scanners = load_scanner_catalog(CATALOG_ROOT)
    assert set(scanners.scanners) == {
        "opengrep",
        "gitleaks",
        "osv-scanner",
        "trivy-config",
        "trivy-vuln",
    }
    argv = resolve_argv(scanners.scanners["opengrep"], {"source": "/source", "rules": "/rules"})
    assert argv[-1] == "/source" and "/rules" in argv


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda s: s["scanners"]["gitleaks"]["argv"].append("{home}"), "unknown argv placeholders"),
        (lambda s: s["scanners"]["opengrep"].update(mounts=[]), "without declaring"),
        (lambda s: s["scanners"]["gitleaks"].update(argv=["dir"]), "source"),
        (lambda s: s["scanners"]["trivy-vuln"].update(network="any"), "Extra inputs"),
    ],
)
def test_invalid_scanner_catalog_fails_closed(tmp_path: Path, mutate, message: str) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "cs"
    root.mkdir()
    document = yaml.safe_load((CATALOG_ROOT / "scanners.yaml").read_text())
    mutate(document)
    (root / "scanners.yaml").write_text(yaml.safe_dump(document))
    with pytest.raises(CodeSecurityCatalogError, match=message):
        load_scanner_catalog(root)


def test_every_rule_is_classified_and_covered_by_a_fixture() -> None:
    ids: list[str] = []
    for rule_file in sorted(_RULES.glob("*.yaml")):
        language = rule_file.stem
        fixture = (_RULES / language).with_suffix(_FIXTURE_SUFFIX[language])
        annotations = set(re.findall(r"ruleid: (\S+)", fixture.read_text()))
        for rule in yaml.safe_load(rule_file.read_text())["rules"]:
            ids.append(rule["id"])
            assert rule["id"].startswith(f"fdai.{'js' if language == 'javascript' else language}.")
            (cwe,) = rule["metadata"]["cwe"]
            number = int(cwe.removeprefix("CWE-"))
            assert catalog().weakness_classes.class_for_cwe(number), rule["id"]
            assert rule["id"] in annotations, f"{rule['id']} has no positive fixture"
    assert len(ids) == len(set(ids)) == 22


@pytest.mark.skipif(
    shutil.which("semgrep") is None and shutil.which("opengrep") is None,
    reason="no rule engine installed",
)
def test_rule_pack_passes_engine_test_mode() -> None:
    import subprocess

    engine = shutil.which("opengrep") or shutil.which("semgrep")
    proc = subprocess.run(  # noqa: S603 - fixed argv over repository fixtures
        [str(engine), "--test", "--metrics=off", str(_RULES)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
