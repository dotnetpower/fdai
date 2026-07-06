"""Unit tests for :mod:`aiopspilot.core.measurement.prompt_probe_cli`."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from aiopspilot.core.measurement.prompt_probe_cli import (
    main,
    resolve_catalog_root,
    run_from_catalog,
)
from aiopspilot.core.measurement.prompt_probe_testing import AbstainResponder

_SCENARIO_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "scenarios"
    / "schema"
    / "scenario.schema.json"
)
_PROMPT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "schema"
    / "prompt.schema.json"
)
_SHIPPED_BASE_YAML = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "base"
    / "t2-cross-check.v1.yaml"
)


def _stage_minimal_catalog(root: Path) -> None:
    """Stage a minimal but complete catalog under ``root/rule-catalog/``.

    Copies the shipped prompt schema + base prompt so the CLI can wire
    a real composer. Scenarios directory has the schema but no
    fixtures - the CLI produces the empty-batch KPI output.
    """

    dst = root / "rule-catalog"
    (dst / "prompts" / "schema").mkdir(parents=True)
    (dst / "prompts" / "schema" / "prompt.schema.json").write_text(_PROMPT_SCHEMA_PATH.read_text())
    (dst / "prompts" / "base").mkdir()
    (dst / "prompts" / "base" / "t2-cross-check.v1.yaml").write_text(_SHIPPED_BASE_YAML.read_text())
    (dst / "prompts" / "scenarios" / "schema").mkdir(parents=True)
    (dst / "prompts" / "scenarios" / "schema" / "scenario.schema.json").write_text(
        _SCENARIO_SCHEMA_PATH.read_text()
    )


class TestResolveCatalogRoot:
    def test_env_override_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "rc"
        target.mkdir()
        monkeypatch.setenv("AIOPSPILOT_CATALOG_ROOT", str(target))
        assert resolve_catalog_root() == target

    def test_env_pointing_at_missing_dir_fails_fast(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AIOPSPILOT_CATALOG_ROOT", str(tmp_path / "nonexistent"))
        with pytest.raises(FileNotFoundError, match="not a directory"):
            resolve_catalog_root()


class TestRunFromCatalog:
    """End-to-end runner against a minimal but real on-disk catalog."""

    @pytest.mark.asyncio
    async def test_empty_scenarios_yields_zero_sample_report(self, tmp_path: Path) -> None:
        _stage_minimal_catalog(tmp_path)
        report = await run_from_catalog(tmp_path / "rule-catalog", responder=AbstainResponder())
        assert report.summary.sample_count == 0

    @pytest.mark.asyncio
    async def test_shipped_scenario_scored_against_abstain_responder(self, tmp_path: Path) -> None:
        """Stage one scenario and prove the abstain responder scores as
        adherence-pass (it returns a valid ``action_type`` string)."""

        import yaml

        _stage_minimal_catalog(tmp_path)
        scenario_body = {
            "id": "abstain-happy",
            "version": 1,
            "capability_id": "t2.reasoner.primary",
            "expected": {
                "required_fields": [
                    {"name": "action_type", "expected_type": "string"},
                    {"name": "params", "expected_type": "object", "non_empty": False},
                ]
            },
            "provenance": {"source": "test"},
        }
        catalog_dir = tmp_path / "rule-catalog" / "prompts" / "scenarios" / "catalog"
        catalog_dir.mkdir()
        (catalog_dir / "abstain-happy.v1.yaml").write_text(
            yaml.safe_dump(scenario_body, sort_keys=False)
        )

        report = await run_from_catalog(tmp_path / "rule-catalog", responder=AbstainResponder())

        assert report.summary.sample_count == 1
        assert report.summary.adherence_pass_rate == pytest.approx(1.0)


class TestMainCli:
    """The synchronous ``main()`` entry point used by ``python -m``."""

    def test_missing_catalog_returns_exit_code_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AIOPSPILOT_CATALOG_ROOT", str(tmp_path / "nope"))
        assert main() == 2

    def test_empty_catalog_prints_one_kpi_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stage_minimal_catalog(tmp_path)
        monkeypatch.setenv("AIOPSPILOT_CATALOG_ROOT", str(tmp_path / "rule-catalog"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main()
        assert exit_code == 0
        # Exactly one JSON row: the ``sample_count`` metric for an
        # empty run. Emitter's other rows are suppressed when
        # sample_count == 0 / no violations / no citations.
        rows = [json.loads(line) for line in buf.getvalue().splitlines()]
        assert len(rows) == 1
        assert rows[0]["metric"] == "prompt.recognition.sample_count"
        assert rows[0]["value"] == 0.0
        assert rows[0]["dimensions"] == {"cli": "prompt_probe"}
        assert rows[0]["unit"] == "count"

    def test_scored_run_emits_multiple_kpi_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import yaml

        _stage_minimal_catalog(tmp_path)
        scenario_body = {
            "id": "s1",
            "version": 1,
            "capability_id": "t2.reasoner.primary",
            "expected": {"required_fields": [{"name": "action_type", "expected_type": "string"}]},
            "provenance": {"source": "test"},
        }
        catalog_dir = tmp_path / "rule-catalog" / "prompts" / "scenarios" / "catalog"
        catalog_dir.mkdir()
        (catalog_dir / "s1.v1.yaml").write_text(yaml.safe_dump(scenario_body, sort_keys=False))
        monkeypatch.setenv("AIOPSPILOT_CATALOG_ROOT", str(tmp_path / "rule-catalog"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = main()

        assert exit_code == 0
        rows = [json.loads(line) for line in buf.getvalue().splitlines()]
        metrics = {row["metric"] for row in rows}
        # Both sample_count and adherence.pass_rate MUST be emitted
        # for a non-empty run.
        assert "prompt.recognition.sample_count" in metrics
        assert "prompt.recognition.adherence.pass_rate" in metrics
