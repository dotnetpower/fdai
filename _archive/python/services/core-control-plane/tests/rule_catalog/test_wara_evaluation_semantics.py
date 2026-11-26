from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fdai.rule_catalog.schema.wara_assessment import canonical_digest
from fdai.rule_catalog.schema.wara_evaluator_binding import WaraEvaluatorBindingCatalog

ROOT = Path(__file__).resolve().parents[4]
ASSESSMENT = ROOT / "rule-catalog/collected/wara-aprl/assessment"


def _generator(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/catalog"))
    spec = importlib.util.spec_from_file_location(
        "build_wara_evaluator_bindings", ROOT / "scripts/catalog/build_wara_evaluator_bindings.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_automated_guid_has_an_exact_review_and_no_manual_query_is_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay, ledger = _generator(monkeypatch).build(ASSESSMENT)
    assert overlay == json.loads((ASSESSMENT / "evaluator-bindings.json").read_text())
    assert ledger == json.loads((ASSESSMENT / "evaluation-semantics.json").read_text())
    parsed = WaraEvaluatorBindingCatalog.model_validate(overlay)
    queries = json.loads((ASSESSMENT / "queries.json").read_text())["queries"]
    automatic = {query["aprl_guid"]: query["body_digest"] for query in queries}
    assert len(ledger["reviews"]) == 143
    assert {
        review["aprl_guid"]: review["query_digest"] for review in ledger["reviews"]
    } == automatic
    assert len(parsed.bindings) == 57
    assert sum(review["decision"] == "t0_rule" for review in ledger["reviews"]) == 1
    assert sum(review["decision"] == "blocked" for review in ledger["reviews"]) == 85
    assert all(binding.observation_requirements for binding in parsed.bindings)
    assert all(
        review["rationale"] and review["blockers"]
        for review in ledger["reviews"]
        if review["binding_status"] == "blocked"
    )
    material = {key: value for key, value in ledger.items() if key != "review_digest"}
    assert canonical_digest(material) == ledger["review_digest"]


def test_scope_and_semantic_counterexamples_remain_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay, ledger = _generator(monkeypatch).build(ASSESSMENT)
    bound = {binding["aprl_guid"] for binding in overlay["bindings"]}
    reviews = {review["aprl_guid"][:8]: review for review in ledger["reviews"]}
    for selector in (
        "1981f704",  # Name collision in a backup join.
        "4f63619f",  # Child ids returned for parent scope.
        "3263a64a",  # Informational shared-disk listing.
        "902c82ff",  # Only the first pool is inspected.
        "dcaf8128",  # False flags are nonempty strings.
        "fa0cf4f5",  # Inverted failure predicate.
        "98bd7098",  # No executable source.
        "302fda08",  # Advisor absence is not satisfaction.
    ):
        review = reviews[selector]
        assert review["decision"] == "blocked"
        assert review["aprl_guid"] not in bound
        assert review["empty_result_meaning"] == "no_query_satisfaction_verdict"


def test_changed_query_generation_requires_fresh_semantic_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _generator(monkeypatch)
    monkeypatch.setattr(module, "AUTOMATED_IDENTITIES_DIGEST", "sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="semantic re-review"):
        module.build(ASSESSMENT)


def test_stored_digest_cannot_hide_modified_kql(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _generator(monkeypatch)
    queries = json.loads((ASSESSMENT / "queries.json").read_text())
    queries["queries"][0]["body_base64"] = "UmVzb3VyY2Vz"  # Resources, not the pinned body.
    original = Path.read_text

    def read_text(path: Path, *args, **kwargs):
        if path == ASSESSMENT / "queries.json":
            return json.dumps(queries)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    with pytest.raises(ValueError, match="query body digest mismatch"):
        module.build(ASSESSMENT)


@pytest.mark.parametrize("duplicate", (False, True))
def test_missing_or_duplicate_semantic_review_cannot_generate_an_overlay(
    monkeypatch: pytest.MonkeyPatch,
    duplicate: bool,
) -> None:
    module = _generator(monkeypatch)
    exact = dict(module.EXACT)
    if duplicate:
        blocked = dict(module.BLOCKED)
        blocked[next(iter(exact))] = "Duplicate review is not an independent review."
        monkeypatch.setattr(module, "BLOCKED", blocked)
    else:
        exact.pop(next(iter(exact)))
        monkeypatch.setattr(module, "EXACT", exact)
    with pytest.raises(ValueError, match="each pinned automated GUID exactly once"):
        module.build(ASSESSMENT)


def _intercept_json(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    material: dict,
) -> None:
    original = Path.read_text

    def read_text(path: Path, *args, **kwargs):
        if path == ASSESSMENT / filename:
            return json.dumps(material)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)


def _with_digest(material: dict, key: str) -> dict:
    material.pop(key)
    material[key] = canonical_digest(material)
    return material


def test_rule_overlay_repin_changes_only_crosswalk_and_overlay_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _generator(monkeypatch)
    original = json.loads((ASSESSMENT / "rule-bindings.json").read_text())
    crosswalk = json.loads((ASSESSMENT / "crosswalk.json").read_text())
    crosswalk["framework_version"] = "2026-10-30"
    _with_digest(crosswalk, "crosswalk_digest")
    _intercept_json(monkeypatch, "crosswalk.json", crosswalk)

    refreshed = module.build_rule_overlay(ASSESSMENT)
    assert refreshed["bindings"] == original["bindings"]
    assert refreshed["source_revision"] == original["source_revision"]
    assert refreshed["crosswalk_digest"] == crosswalk["crosswalk_digest"]
    assert refreshed["overlay_digest"] != original["overlay_digest"]
    assert {
        key: value
        for key, value in refreshed.items()
        if key not in {"crosswalk_digest", "overlay_digest"}
    } == {
        key: value
        for key, value in original.items()
        if key not in {"crosswalk_digest", "overlay_digest"}
    }


@pytest.mark.parametrize(
    "change",
    ("rule_version", "rule_digest", "query_digest", "capability", "missing_binding"),
)
def test_changed_rule_binding_material_requires_explicit_review(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    module = _generator(monkeypatch)
    raw = json.loads((ASSESSMENT / "rule-bindings.json").read_text())
    if change == "capability":
        raw["bindings"][0]["capability"]["inventory_fields"] = ["other_field"]
    elif change == "missing_binding":
        raw["bindings"] = []
    else:
        raw["bindings"][0][change] = "9.9.9" if change == "rule_version" else "sha256:" + "0" * 64
    _with_digest(raw, "overlay_digest")
    _intercept_json(monkeypatch, "rule-bindings.json", raw)
    with pytest.raises(ValueError, match="reviewed Rule binding material changed"):
        module.build_rule_overlay(ASSESSMENT)


def test_changed_release_rule_body_cannot_be_repaired_by_repinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _generator(monkeypatch)
    rules = module._release_rules(ROOT)
    original = json.loads((ASSESSMENT / "rule-bindings.json").read_text())
    rule_id = original["bindings"][0]["rule_id"]
    changed = []
    for rule in rules:
        if rule.id == rule_id:
            raw = rule.model_dump(mode="json")
            raw["severity"] = "low" if raw["severity"] == "critical" else "critical"
            rule = type(rule).model_validate(raw)
        changed.append(rule)
    monkeypatch.setattr(module, "_release_rules", lambda _root: tuple(changed))
    with pytest.raises(ValueError, match="unavailable revision"):
        module.build_rule_overlay(ASSESSMENT)


def test_rule_validation_failure_happens_before_any_output_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _generator(monkeypatch)
    raw = json.loads((ASSESSMENT / "rule-bindings.json").read_text())
    raw["bindings"][0]["rule_version"] = "9.9.9"
    _with_digest(raw, "overlay_digest")
    _intercept_json(monkeypatch, "rule-bindings.json", raw)
    monkeypatch.setattr(module.sys, "argv", ["build_wara_evaluator_bindings.py"])
    writes = []
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: writes.append(args))
    with pytest.raises(ValueError, match="reviewed Rule binding material changed"):
        module.main()
    assert not writes


def test_check_mode_detects_stale_rule_pin_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _generator(monkeypatch)
    raw = json.loads((ASSESSMENT / "rule-bindings.json").read_text())
    raw["crosswalk_digest"] = "sha256:" + "0" * 64
    _with_digest(raw, "overlay_digest")
    _intercept_json(monkeypatch, "rule-bindings.json", raw)
    monkeypatch.setattr(module.sys, "argv", ["build_wara_evaluator_bindings.py", "--check"])
    writes = []
    monkeypatch.setattr(Path, "write_text", lambda *args, **kwargs: writes.append(args))
    assert module.main() == 1
    assert not writes
