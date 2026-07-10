"""Tests for :mod:`fdai.delivery.provisioning.terraform_bridge`.

The bridge is a pure fold from Terraform ``-json`` lines to
``provision.*`` events, so the tests replay recorded log-line sequences and
assert the emitted events. No I/O, no clock.
"""

from __future__ import annotations

import json

from fdai.delivery.provisioning.terraform_bridge import (
    TerraformProvisionBridge,
    console_url_from_outputs,
    parse_json_line,
)
from fdai.delivery.read_api.provision_stream import ProvisionPhase


def _line(record: dict[str, object]) -> str:
    return json.dumps(record)


def _plan_summary(add: int = 0, change: int = 0, remove: int = 0) -> dict[str, object]:
    return {
        "type": "change_summary",
        "changes": {"add": add, "change": change, "remove": remove, "operation": "plan"},
    }


def _apply_complete(addr: str) -> dict[str, object]:
    return {"type": "apply_complete", "hook": {"resource": {"addr": addr}, "action": "create"}}


def _apply_progress(addr: str, elapsed: float) -> dict[str, object]:
    return {
        "type": "apply_progress",
        "hook": {"resource": {"addr": addr}, "action": "create", "elapsed_seconds": elapsed},
    }


# ---------------------------------------------------------------------------
# parse_json_line
# ---------------------------------------------------------------------------


class TestParseJsonLine:
    def test_valid_json(self) -> None:
        assert parse_json_line('{"type":"version"}') == {"type": "version"}

    def test_non_json_line_returns_none(self) -> None:
        assert parse_json_line("Terraform will perform the following actions:") is None

    def test_blank_line_returns_none(self) -> None:
        assert parse_json_line("   ") is None

    def test_json_array_returns_none(self) -> None:
        assert parse_json_line("[1,2,3]") is None

    def test_malformed_json_returns_none(self) -> None:
        assert parse_json_line('{"type": ') is None


# ---------------------------------------------------------------------------
# console_url_from_outputs
# ---------------------------------------------------------------------------


class TestConsoleUrl:
    def test_reads_value_field(self) -> None:
        outputs = {"console_url": {"value": "https://c.example.com", "type": "string"}}
        assert console_url_from_outputs(outputs) == "https://c.example.com"

    def test_flat_string_value(self) -> None:
        assert console_url_from_outputs({"console_url": "https://c.example.com"}) == (
            "https://c.example.com"
        )

    def test_missing_key_returns_none(self) -> None:
        assert console_url_from_outputs({"other": {"value": "x"}}) is None

    def test_custom_key(self) -> None:
        outputs = {"portal": {"value": "https://p.example.com"}}
        assert console_url_from_outputs(outputs, key="portal") == "https://p.example.com"


# ---------------------------------------------------------------------------
# TerraformProvisionBridge - progress fraction
# ---------------------------------------------------------------------------


class TestProgressFraction:
    def test_plan_summary_sets_denominator(self) -> None:
        bridge = TerraformProvisionBridge()
        bridge.feed(_line(_plan_summary(add=4)))
        events = bridge.feed(_line(_apply_complete("azurerm_x.a")))
        assert len(events) == 1
        assert events[0].phase is ProvisionPhase.PROGRESS
        assert events[0].fraction == 0.25

    def test_fraction_climbs_to_one(self) -> None:
        bridge = TerraformProvisionBridge()
        bridge.feed(_line(_plan_summary(add=2)))
        bridge.feed(_line(_apply_complete("a")))
        events = bridge.feed(_line(_apply_complete("b")))
        assert events[0].fraction == 1.0

    def test_fraction_capped_at_one(self) -> None:
        bridge = TerraformProvisionBridge()
        bridge.feed(_line(_plan_summary(add=1)))
        bridge.feed(_line(_apply_complete("a")))
        events = bridge.feed(_line(_apply_complete("b")))  # more than planned
        assert events[0].fraction == 1.0

    def test_no_plan_summary_fraction_zero(self) -> None:
        bridge = TerraformProvisionBridge()
        events = bridge.feed(_line(_apply_complete("a")))
        assert events[0].fraction == 0.0

    def test_duplicate_apply_complete_not_double_counted(self) -> None:
        bridge = TerraformProvisionBridge()
        bridge.feed(_line(_plan_summary(add=2)))
        first = bridge.feed(_line(_apply_complete("a")))
        dup = bridge.feed(_line(_apply_complete("a")))  # re-emit for same addr
        assert first[0].fraction == 0.5
        assert dup == []  # no second progress, fraction not inflated

    def test_zero_replan_does_not_wipe_denominator(self) -> None:
        bridge = TerraformProvisionBridge()
        bridge.feed(_line(_plan_summary(add=4)))
        bridge.feed(_line(_plan_summary()))  # refresh/no-op replan reports 0
        events = bridge.feed(_line(_apply_complete("a")))
        assert events[0].fraction == 0.25  # denominator preserved


# ---------------------------------------------------------------------------
# TerraformProvisionBridge - waiting / resumed
# ---------------------------------------------------------------------------


class TestWaitingResumed:
    def test_slow_progress_emits_waiting_once(self) -> None:
        bridge = TerraformProvisionBridge(waiting_threshold_seconds=30.0)
        first = bridge.feed(_line(_apply_progress("db", 31)))
        second = bridge.feed(_line(_apply_progress("db", 45)))
        assert len(first) == 1
        assert first[0].phase is ProvisionPhase.WAITING
        assert first[0].node == "db"
        assert second == []  # already waiting, no duplicate

    def test_fast_progress_no_waiting(self) -> None:
        bridge = TerraformProvisionBridge(waiting_threshold_seconds=30.0)
        assert bridge.feed(_line(_apply_progress("db", 5))) == []

    def test_waiting_then_complete_emits_resumed(self) -> None:
        bridge = TerraformProvisionBridge(waiting_threshold_seconds=30.0)
        bridge.feed(_line(_plan_summary(add=1)))
        bridge.feed(_line(_apply_progress("db", 31)))
        events = bridge.feed(_line(_apply_complete("db")))
        phases = [e.phase for e in events]
        assert ProvisionPhase.RESUMED in phases
        assert ProvisionPhase.PROGRESS in phases


# ---------------------------------------------------------------------------
# TerraformProvisionBridge - done / failed
# ---------------------------------------------------------------------------


class TestDoneFailed:
    def test_outputs_then_apply_summary_emits_done(self) -> None:
        bridge = TerraformProvisionBridge()
        bridge.feed(
            _line(
                {
                    "type": "outputs",
                    "outputs": {"console_url": {"value": "https://c.example.com"}},
                }
            )
        )
        events = bridge.feed(
            _line({"type": "change_summary", "changes": {"add": 1, "operation": "apply"}})
        )
        assert len(events) == 1
        assert events[0].phase is ProvisionPhase.DONE
        assert events[0].console_url == "https://c.example.com"
        assert events[0].fraction == 1.0

    def test_done_emitted_once(self) -> None:
        bridge = TerraformProvisionBridge()
        outputs = _line(
            {"type": "outputs", "outputs": {"console_url": {"value": "https://c.example.com"}}}
        )
        apply_summary = _line(
            {"type": "change_summary", "changes": {"add": 1, "operation": "apply"}}
        )
        bridge.feed(outputs)
        first = bridge.feed(apply_summary)
        second = bridge.feed(apply_summary)
        assert len(first) == 1
        assert second == []
        assert bridge.finalize() == []  # already done

    def test_done_deferred_until_outputs_captured(self) -> None:
        # Real Terraform order: apply change_summary arrives BEFORE outputs.
        # done MUST wait so it carries the console_url, not emit early w/ None.
        bridge = TerraformProvisionBridge()
        early = bridge.feed(
            _line({"type": "change_summary", "changes": {"add": 1, "operation": "apply"}})
        )
        assert early == []  # deferred, no premature done
        events = bridge.feed(
            _line(
                {"type": "outputs", "outputs": {"console_url": {"value": "https://c.example.com"}}}
            )
        )
        assert len(events) == 1
        assert events[0].phase is ProvisionPhase.DONE
        assert events[0].console_url == "https://c.example.com"

    def test_finalize_flushes_done_without_outputs(self) -> None:
        bridge = TerraformProvisionBridge()
        assert (
            bridge.feed(
                _line({"type": "change_summary", "changes": {"add": 1, "operation": "apply"}})
            )
            == []
        )
        events = bridge.finalize()
        assert len(events) == 1
        assert events[0].phase is ProvisionPhase.DONE
        assert events[0].console_url is None
        assert bridge.finalize() == []  # idempotent

    def test_finalize_noop_when_apply_never_finished(self) -> None:
        # A failed / aborted run never emits change_summary(apply); finalize
        # MUST NOT paper over it with a fake success.
        bridge = TerraformProvisionBridge()
        bridge.feed(_line(_apply_complete("a")))
        assert bridge.finalize() == []

    def test_apply_errored_emits_failed(self) -> None:
        bridge = TerraformProvisionBridge()
        events = bridge.feed(
            _line({"type": "apply_errored", "hook": {"resource": {"addr": "azurerm_x.a"}}})
        )
        assert len(events) == 1
        assert events[0].phase is ProvisionPhase.FAILED
        assert events[0].node == "azurerm_x.a"

    def test_error_diagnostic_emits_failed(self) -> None:
        bridge = TerraformProvisionBridge()
        events = bridge.feed(
            _line(
                {
                    "type": "diagnostic",
                    "diagnostic": {"severity": "error", "summary": "quota exceeded"},
                }
            )
        )
        assert len(events) == 1
        assert events[0].phase is ProvisionPhase.FAILED
        assert events[0].reason == "quota exceeded"

    def test_warning_diagnostic_ignored(self) -> None:
        bridge = TerraformProvisionBridge()
        events = bridge.feed(
            _line(
                {
                    "type": "diagnostic",
                    "diagnostic": {"severity": "warning", "summary": "deprecated"},
                }
            )
        )
        assert events == []


# ---------------------------------------------------------------------------
# End-to-end replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_full_apply_sequence(self) -> None:
        bridge = TerraformProvisionBridge()
        lines = [
            _line({"type": "version", "terraform": "1.9.0"}),
            _line("not-json-noise"),  # skipped
            _line(_plan_summary(add=3)),
            _line(_apply_complete("azurerm_resource_group.main")),
            _line(_apply_complete("azurerm_postgresql_flexible_server.db")),
            _line(_apply_complete("azurerm_container_app.core")),
            # Realistic order: apply change_summary BEFORE outputs.
            _line({"type": "change_summary", "changes": {"add": 3, "operation": "apply"}}),
            _line({"type": "outputs", "outputs": {"console_url": {"value": "https://x"}}}),
        ]
        collected = []
        for raw in lines:
            collected.extend(bridge.feed(raw))
        collected.extend(bridge.finalize())
        phases = [e.phase for e in collected]
        assert phases == [
            ProvisionPhase.PROGRESS,
            ProvisionPhase.PROGRESS,
            ProvisionPhase.PROGRESS,
            ProvisionPhase.DONE,
        ]
        assert collected[-1].console_url == "https://x"
        assert collected[-1].fraction == 1.0
        # fractions climb monotonically
        fractions = [e.fraction for e in collected if e.phase is ProvisionPhase.PROGRESS]
        assert fractions == sorted(fractions)
