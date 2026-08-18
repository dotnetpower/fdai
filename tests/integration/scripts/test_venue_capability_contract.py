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
