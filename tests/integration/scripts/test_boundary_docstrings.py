"""Fixture tests for the reviewed boundary-docstring checker."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _ROOT / "scripts/quality/architecture/check-boundary-docstrings.py"


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and checker
        [
            sys.executable,
            str(_CHECKER),
            "--root",
            str(root),
            "--scopes",
            "scopes.txt",
            "--exclusions",
            "exclusions.txt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _docstring(*, empty: str | None = None) -> str:
    sections = []
    for section in (
        "Responsibility",
        "Boundary",
        "Authority and state",
        "Dependencies",
        "Deployment",
    ):
        value = "" if section == empty else f"{section} details."
        sections.append(f"{section}:\n{value}")
    return '"""' + "\n\n".join(sections) + '\n"""\n'


def test_complete_enforced_docstring_passes(tmp_path: Path) -> None:
    path = "src/example/boundary.py"
    _write(tmp_path, path, _docstring())
    _write(tmp_path, "scopes.txt", f"# Reviewed boundary.\nenforce|{path}\n")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout


def test_missing_section_fails_enforced_scope(tmp_path: Path) -> None:
    path = "src/example/boundary.py"
    source = _docstring().replace("Deployment:\nDeployment details.\n", "")
    _write(tmp_path, path, source)
    _write(tmp_path, "scopes.txt", f"# Reviewed boundary.\nenforce|{path}\n")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "missing section 'Deployment'" in result.stdout


def test_empty_section_is_reported_without_failure(tmp_path: Path) -> None:
    path = "src/example/boundary.py"
    _write(tmp_path, path, _docstring(empty="Boundary"))
    _write(tmp_path, "scopes.txt", f"# Initial report scope.\nreport|{path}\n")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "empty section 'Boundary'" in result.stdout


def test_reviewed_exclusion_suppresses_existing_gap(tmp_path: Path) -> None:
    path = "src/example/boundary.py"
    _write(tmp_path, path, '"""Legacy boundary."""\n')
    _write(tmp_path, "scopes.txt", f"# Initial report scope.\nreport|{path}\n")
    _write(tmp_path, "exclusions.txt", f"# Reviewed legacy exception.\n{path}\n")

    result = _run(tmp_path)

    assert result.returncode == 0, result.stdout
    assert "excluded=1" in result.stdout


def test_stale_exclusion_fails_when_docstring_is_fixed(tmp_path: Path) -> None:
    path = "src/example/boundary.py"
    _write(tmp_path, path, _docstring())
    _write(tmp_path, "scopes.txt", f"# Initial report scope.\nreport|{path}\n")
    _write(tmp_path, "exclusions.txt", f"# Obsolete exception.\n{path}\n")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "stale exclusion" in result.stdout


def test_missing_report_scope_fails_as_configuration_drift(tmp_path: Path) -> None:
    path = "src/example/missing.py"
    _write(tmp_path, "scopes.txt", f"# Reviewed boundary.\nreport|{path}\n")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "reviewed scope file is missing" in result.stdout


def test_missing_excluded_file_fails_as_stale(tmp_path: Path) -> None:
    path = "src/example/missing.py"
    _write(tmp_path, "scopes.txt", f"# Reviewed boundary.\nreport|{path}\n")
    _write(tmp_path, "exclusions.txt", f"# Reviewed exception.\n{path}\n")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "excluded file is missing" in result.stdout


def test_exclusion_outside_reviewed_scope_fails(tmp_path: Path) -> None:
    scoped = "src/example/scoped.py"
    excluded = "src/example/unscoped.py"
    _write(tmp_path, scoped, _docstring())
    _write(tmp_path, excluded, '"""Legacy package."""\n')
    _write(tmp_path, "scopes.txt", f"# Reviewed boundary.\nreport|{scoped}\n")
    _write(tmp_path, "exclusions.txt", f"# Invalid exception.\n{excluded}\n")

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "exclusion is outside reviewed scopes" in result.stdout
