"""Best-practice directory catalog tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fdai.rule_catalog.schema.best_practice_catalog import (
    BestPracticeCatalogError,
    load_best_practice_catalog,
)
from fdai.shared.contracts.models import RequirementKind


def _control(control_id: str = "RE:09") -> dict[str, object]:
    slug = control_id.lower().replace(":", "-")
    return {
        "schema_version": "1.0.0",
        "kind": "best-practice",
        "id": f"azure-waf.reliability.{slug}",
        "version": "1.0.0",
        "framework": "azure-waf",
        "control_id": control_id,
        "title": "Test disaster recovery",
        "rationale": "Recovery evidence must demonstrate approved objectives.",
        "severity": "high",
        "category": "reliability",
        "requirements": [
            {"kind": "rule", "ref": "postgresql-server.point-in-time-restore"},
            {"kind": "drill", "ref": "restore-failover-drill", "freshness_days": 180},
        ],
        "provenance": {
            "source_url": "https://learn.microsoft.com/azure/well-architected/reliability/checklist",
            "resolved_ref": "example-revision",
            "content_hash": "sha256:example",
            "license": "CC-BY-4.0",
            "redistribution": "embeddable",
            "retrieved_at": "2026-07-29T00:00:00Z",
        },
    }


def _write(root: Path, raw: dict[str, object], *, name: str | None = None) -> None:
    path = root / f"{name or raw['id']}.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _known() -> dict[RequirementKind, set[str]]:
    return {
        RequirementKind.RULE: {"postgresql-server.point-in-time-restore"},
        RequirementKind.DRILL: {"restore-failover-drill"},
    }


def test_loads_catalog_with_complete_reference_registries(tmp_path: Path) -> None:
    _write(tmp_path, _control())

    catalog = load_best_practice_catalog(tmp_path, known_refs=_known())

    assert [control.control_id for control in catalog] == ["RE:09"]


def test_strict_mode_rejects_missing_registry(tmp_path: Path) -> None:
    _write(tmp_path, _control())

    with pytest.raises(BestPracticeCatalogError, match="no known-reference registry"):
        load_best_practice_catalog(
            tmp_path,
            known_refs={RequirementKind.RULE: _known()[RequirementKind.RULE]},
        )


def test_rejects_unknown_reference_and_filename_mismatch(tmp_path: Path) -> None:
    raw = _control()
    requirements = raw["requirements"]
    assert isinstance(requirements, list)
    requirements[0]["ref"] = "missing.rule"
    _write(tmp_path, raw, name="wrong-name")

    with pytest.raises(BestPracticeCatalogError) as error:
        load_best_practice_catalog(tmp_path, known_refs=_known())

    messages = [issue.message for issue in error.value.issues]
    assert any("file stem MUST equal" in message for message in messages)
    assert any("unknown rule reference" in message for message in messages)


def test_rejects_duplicate_framework_control(tmp_path: Path) -> None:
    first = _control()
    second = _control()
    second["id"] = "azure-waf.reliability.re-09-alternate"
    _write(tmp_path, first)
    _write(tmp_path, second)

    with pytest.raises(BestPracticeCatalogError, match="duplicate framework control"):
        load_best_practice_catalog(tmp_path, known_refs=_known())
