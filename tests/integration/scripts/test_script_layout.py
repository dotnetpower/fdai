"""Repository script layout regression tests."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_ROOT = _REPO_ROOT / "scripts"


def test_scripts_root_contains_only_stable_entrypoints() -> None:
    root_files = {path.name for path in _SCRIPTS_ROOT.iterdir() if path.is_file()}

    assert root_files == {
        ".check-file-loc.allowlist",
        ".check-file-loc.baseline",
        "README.md",
        "__init__.py",
        "verify.sh",
    }


def test_script_domains_are_present() -> None:
    domain_directories = {path.name for path in _SCRIPTS_ROOT.iterdir() if path.is_dir()}

    assert {
        "automation",
        "catalog",
        "deployment",
        "governance",
        "integrity",
        "lib",
        "quality",
    } <= domain_directories


def test_verify_declares_every_required_gate() -> None:
    verify = (_SCRIPTS_ROOT / "verify.sh").read_text(encoding="utf-8")
    required_invocations = (
        '"catalog-parity"',
        '"stewardship"',
        '"chaos-scenarios"',
        '"architecture-review"',
        '"derived-sources"',
        '"framework-integrity"',
    )

    for invocation in required_invocations:
        assert verify.count(invocation) == 1
    assert "if [[ -f scripts/" not in verify
    assert "if [[ -x scripts/" not in verify
