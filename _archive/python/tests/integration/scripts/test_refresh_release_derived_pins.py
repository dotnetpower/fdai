"""Release-pin generation preserves reviewed inputs and immutable receipt history."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = runpy.run_path(str(ROOT / "scripts/catalog/refresh-release-derived-pins.py"))
Update = MODULE["Update"]
apply_updates = MODULE["apply_updates"]


def test_check_is_read_only_and_write_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "source.json"
    path.write_bytes(b"before")
    updates = (Update(path, b"before", b"after"),)
    assert apply_updates(updates, write=False) == 1
    assert path.read_bytes() == b"before"
    assert apply_updates(updates, write=True) == 1
    assert path.read_bytes() == b"after"
    assert apply_updates((Update(path, b"after", b"after"),), write=True) == 0


@pytest.mark.parametrize("problem", ["changed", "immutable", "duplicate", "symlink", "dangling"])
def test_invalid_plan_writes_no_earlier_output(tmp_path: Path, problem: str) -> None:
    first = tmp_path / "first.json"
    other = tmp_path / "other.json"
    first.write_bytes(b"first")
    other.write_bytes(b"original")
    pending = Update(first, b"first", b"replacement")
    if problem == "changed":
        last = Update(other, b"stale", b"new")
    elif problem == "immutable":
        last = Update(other, b"original", b"new", immutable=True)
    elif problem == "duplicate":
        last = pending
    else:
        link = tmp_path / "link.json"
        link.symlink_to(other if problem == "symlink" else tmp_path / "absent.json")
        last = Update(link, b"original", b"new")
    with pytest.raises(ValueError):
        apply_updates((pending, last), write=True)
    assert first.read_bytes() == b"first"
    assert other.read_bytes() == b"original"
    assert not (tmp_path / "absent.json").exists()


def test_new_receipt_never_deletes_old_receipt(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_bytes(b"retained")
    assert apply_updates((Update(new, None, b"measured", immutable=True),), write=True) == 1
    assert old.read_bytes() == b"retained"
    assert new.read_bytes() == b"measured"


def test_held_out_cases_keep_original_digest_and_disjoint_queries() -> None:
    from fdai.rule_catalog.schema.rule_semantic_evaluation import _dataset_digest

    cases = MODULE["held_out_cases"]()
    assert len(cases) == 7
    assert _dataset_digest(cases) == (
        "sha256:1307e83d264c8c0b6fdc4342f840b51cebe18f930ca4bd9242387052da54d6de"
    )
    assert len({case.digest for case in cases}) == 7


def test_source_snapshot_detects_policy_edits_and_new_inputs(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    policy = config / "rule-semantic-evaluation.json"
    policy.write_text("{}")
    snapshot = MODULE["source_snapshot"]
    before = snapshot(tmp_path)
    policy.write_text('{"changed":true}')
    after = snapshot(tmp_path)
    assert before != after
    catalog = tmp_path / "rule-catalog" / "action-types"
    catalog.mkdir(parents=True)
    (catalog / "new.yaml").write_text("name: example")
    assert snapshot(tmp_path) != after


def test_cost_profile_refresh_updates_exact_declaration_refs() -> None:
    from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
    from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

    ontology = load_ontology_catalog(
        ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=ROOT / "rule-catalog/probes",
    )
    profile_path = (
        ROOT / "extensions/cost-governance/src/fdai_cost_governance/resources/semantic-profile.json"
    )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    refreshed = MODULE["refresh_profile_release"](profile, ontology)

    release = ontology.build_release()
    expected = next(
        item.model_dump(mode="json")
        for item in release.declarations
        if item.kind.value == "object" and item.name == "BusinessService"
    )
    actual = next(
        item
        for item in refreshed["declarations"]
        if item["kind"] == "object" and item["name"] == "BusinessService"
    )
    assert refreshed["ontology_release_digest"] == release.digest
    assert actual == expected
