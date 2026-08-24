from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/quality/architecture/check-property-semantic-coverage.py"
    spec = importlib.util.spec_from_file_location("check_property_semantic_coverage", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules, so register before executing.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_shipped_catalog_coverage_is_measured_and_documented() -> None:
    module = _load_module()

    coverage, violations = module.measure(REPO_ROOT)

    assert violations == ()
    assert coverage.reviewed_count >= module.REVIEWED_REFERENCE_FLOOR
    assert coverage.reviewed_count == coverage.evaluated_count
    assert coverage.gaps == ()
    assert module._check_documents(REPO_ROOT, coverage, update=False) == ()


def test_documented_block_states_the_measured_numbers() -> None:
    module = _load_module()
    coverage, _ = module.measure(REPO_ROOT)

    for relative in module.DOCUMENTS:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        block = module._render_block(coverage, relative)
        assert block in text
        assert str(coverage.evaluated_count) in block
        assert str(coverage.reviewed_count) in block
        assert coverage.percent in block


def test_stale_documentation_fails_without_update(tmp_path: Path) -> None:
    module = _load_module()
    coverage, _ = module.measure(REPO_ROOT)
    for relative in module.DOCUMENTS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f"{module.BEGIN_MARKER}\nstale text\n{module.END_MARKER}\n",
            encoding="utf-8",
        )

    failures = module._check_documents(tmp_path, coverage, update=False)

    assert len(failures) == len(module.DOCUMENTS)
    assert module._check_documents(tmp_path, coverage, update=True) == ()
    assert module._check_documents(tmp_path, coverage, update=False) == ()


def test_gap_ranking_prefers_shared_paths_then_rule_use_then_unit_risk() -> None:
    module = _load_module()

    shared = module.RankedGap(
        reference="property.a.shared",
        provider_path_count=5,
        decision_rule_count=1,
        unit_risk=False,
    )
    reused = module.RankedGap(
        reference="property.b.reused",
        provider_path_count=1,
        decision_rule_count=3,
        unit_risk=False,
    )
    risky = module.RankedGap(
        reference="property.c.risky_percent",
        provider_path_count=1,
        decision_rule_count=1,
        unit_risk=True,
    )

    assert shared.score > reused.score > risky.score


def test_every_declared_provider_path_has_shipped_rule_evidence() -> None:
    module = _load_module()

    coverage, violations = module.measure(REPO_ROOT)
    evaluated = {item.reference for item in coverage.evaluated}

    assert violations == ()
    assert set(coverage.reviewed_references) <= evaluated
