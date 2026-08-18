from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-venue-capability-contract.py"
    spec = importlib.util.spec_from_file_location("venue_capability_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_source_tree_resolves_the_venue_in_one_module() -> None:
    module = _load_module()

    assert module.main([]) == 0


def test_a_reintroduced_ad_hoc_venue_read_fails_the_gate(tmp_path: Path) -> None:
    module = _load_module()
    contract = tmp_path / "venue.py"
    contract.write_text("VENUE = 'deployed'\n", encoding="utf-8")
    offender = tmp_path / "offender.py"
    offender.write_text(
        'import os\nvenue = os.environ.get("FDAI_EXECUTION_VENUE", "deployed")\n',
        encoding="utf-8",
    )

    findings = module._violations(tmp_path, contract)

    assert len(findings) == 1
    assert "offender.py:2" in findings[0]


def test_a_reintroduced_venue_literal_comparison_fails_the_gate(tmp_path: Path) -> None:
    module = _load_module()
    contract = tmp_path / "venue.py"
    contract.write_text("VENUE = 'deployed'\n", encoding="utf-8")
    offender = tmp_path / "offender.py"
    offender.write_text('use_tls = venue == "deployed"\n', encoding="utf-8")

    findings = module._violations(tmp_path, contract)

    assert len(findings) == 1
    assert "compares a venue literal" in findings[0]


def test_the_contract_module_itself_is_exempt(tmp_path: Path) -> None:
    module = _load_module()
    contract = tmp_path / "venue.py"
    contract.write_text(
        'EXECUTION_VENUE_ENV = "FDAI_EXECUTION_VENUE"\nlocal = raw == "local"\n',
        encoding="utf-8",
    )

    assert module._violations(tmp_path, contract) == []


def test_the_gate_scans_every_service_source_tree() -> None:
    """A gate whose scope can shrink silently proves nothing about the trees it dropped.

    `main([])` only reports the trees it was given, so this derives the expected set from the
    repository layout instead of trusting the table.
    """

    module = _load_module()
    scanned = {path.resolve() for path in module.SCANNED_TREES}

    expected = {(REPO_ROOT / "packages/service-contracts/src/fdai_service_contracts").resolve()}
    for service in sorted((REPO_ROOT / "services").iterdir()):
        source_root = service / "src"
        if not source_root.is_dir():
            continue
        packages = [
            child for child in sorted(source_root.iterdir()) if (child / "__init__.py").is_file()
        ]
        assert packages, f"{service.name} has no importable source package"
        expected.update(package.resolve() for package in packages)

    # Non-vacuity: an empty expectation would make the equality trivially satisfiable.
    assert len(expected) >= 6, sorted(str(path) for path in expected)
    assert scanned == expected, {
        "unscanned": sorted(str(path) for path in expected - scanned),
        "unexpected": sorted(str(path) for path in scanned - expected),
    }
