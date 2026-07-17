from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from fdai.core.chaos.scenario_catalog import load_all

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ingest-kubernetes-docs-catalog.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ingest_kubernetes_docs_catalog", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ingester_is_idempotent_and_outputs_schema_valid_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    root = tmp_path / "chaos-scenarios"
    schema = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "schema"
    (root / "schema").mkdir(parents=True)
    (root / "schema" / "chaos-scenario.schema.json").write_bytes(
        (schema / "chaos-scenario.schema.json").read_bytes()
    )
    out = root / "collected" / "kubernetes-docs"
    monkeypatch.setattr(module, "_OUT_DIR", out)

    assert module.main() == 0
    first = {path.name: path.read_bytes() for path in out.glob("*.yaml")}
    assert module.main() == 0

    assert len(first) == 3
    assert first == {path.name: path.read_bytes() for path in out.glob("*.yaml")}
    entries = load_all(root)
    assert {entry.expected_signal for entry in entries} == {
        "backend_health",
        "request_failure",
        "rollout_stall",
    }
    assert all("license=CC-BY-4.0" in entry.spec["provenance"]["source_ref"] for entry in entries)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"source_url": "https://example.com/postmortem"}, "unsupported_source_url"),
        ({"source_section": ""}, "missing_source_section"),
        ({"expected_signal": "unknown"}, "unknown_expected_signal"),
        ({"expected_signal": "member_hotspot"}, "rca_only_signal_not_scenario_eligible"),
    ],
)
def test_ingester_rejects_unsupported_or_ambiguous_mappings(
    changes: dict[str, str],
    reason: str,
) -> None:
    module = _load_script()
    with pytest.raises(ValueError, match=reason):
        module._validate_entry(replace(module._ENTRIES[0], **changes))
