"""RunRunbookTool + ActivateBreakGlassTool contract tests (Wave W1.1).

Invariants asserted here:

- RunRunbookTool:
  * satisfies SystemConsoleTool Protocol
  * static rbac_floor is Contributor (dry-run path); live path
    (``dry_run=False``) refused unless principal is Owner
  * unknown runbook name -> status='error', audit with error_kind='not_found'
  * registry error -> status='error', audit with error_kind matching
  * happy dry-run -> status='ok', audit records dry_run=True
  * happy live run (Owner) -> status='ok', audit records dry_run=False
    and mode='enforce'
- ActivateBreakGlassTool:
  * satisfies SystemConsoleTool Protocol
  * rbac_floor is Reader (any authenticated)
  * short reason -> refused with refusal_kind='short_reason'
  * secret pattern -> reason redacted BEFORE audit
  * expiry <60 or > max_ttl -> refused
  * pager delivery error -> grant refused with refusal_kind='pager_*'
    (fail-closed on notification, chat invariant 7)
  * pager 'no channel configured' -> grant refused
  * happy path -> pager_receipt in audit + return payload
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aiopspilot.core.conversation import Principal, Role
from aiopspilot.core.conversation.tools import SystemConsoleTool
from aiopspilot.core.conversation.write_tools import (
    ActivateBreakGlassTool,
    AuditWriter,
    RunRunbookTool,
)
from aiopspilot.shared.providers.break_glass_pager import (
    BreakGlassDeliveryError,
    BreakGlassNoChannelError,
)
from aiopspilot.shared.providers.runbook_registry import (
    RunbookExecutionError,
    RunbookResult,
)
from aiopspilot.shared.providers.testing import (
    InMemoryBreakGlassPager,
    InMemoryRunbookRegistry,
    InMemoryStateStore,
)


def _principal(*, role: Role = Role.CONTRIBUTOR, oid: str = "op-oid") -> Principal:
    return Principal(id=oid, role=role, display_name="Operator")


def _unwrap(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        inner = record.get("entry")
        if isinstance(inner, dict) and ("previous_hash" in record or "entry_hash" in record):
            return inner
        return record
    return dict(record)


# ---------------------------------------------------------------------------
# RunRunbookTool - protocol + argument shape
# ---------------------------------------------------------------------------


def _build_run_tool(
    registry: InMemoryRunbookRegistry | None = None,
) -> tuple[RunRunbookTool, InMemoryRunbookRegistry, InMemoryStateStore]:
    reg = registry if registry is not None else InMemoryRunbookRegistry()
    store = InMemoryStateStore()
    tool = RunRunbookTool(registry=reg, audit_writer=AuditWriter(audit_store=store))
    return tool, reg, store


class TestRunRunbookProtocol:
    def test_satisfies_protocol(self) -> None:
        tool, _, _ = _build_run_tool()
        assert isinstance(tool, SystemConsoleTool)

    def test_rbac_floor_is_contributor(self) -> None:
        tool, _, _ = _build_run_tool()
        assert tool.rbac_floor is Role.CONTRIBUTOR

    def test_side_effect_class_is_execute(self) -> None:
        tool, _, _ = _build_run_tool()
        assert tool.side_effect_class == "execute"


class TestRunRunbookArguments:
    def test_missing_name_errors(self) -> None:
        tool, _, _ = _build_run_tool()
        r = tool.call(arguments={}, principal=_principal())
        assert r.status == "error"

    def test_params_must_be_mapping(self) -> None:
        tool, _, _ = _build_run_tool()
        r = tool.call(
            arguments={"name": "x", "params": "not-a-mapping"},
            principal=_principal(),
        )
        assert r.status == "error"

    def test_dry_run_must_be_bool(self) -> None:
        tool, _, _ = _build_run_tool()
        r = tool.call(
            arguments={"name": "x", "dry_run": "yes"},
            principal=_principal(),
        )
        assert r.status == "error"


class TestRunRunbookDryRun:
    def test_happy_dry_run_ok_and_audits(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register(
            "db_dr_drill",
            lambda params, dry_run: RunbookResult(
                ok=True,
                summary=f"planned drill ({'dry' if dry_run else 'live'})",
                detail={"plan_id": "p-1"},
            ),
        )
        tool, _, store = _build_run_tool(reg)
        r = tool.call(
            arguments={"name": "db_dr_drill", "params": {"env": "dev"}},
            principal=_principal(),
        )
        assert r.status == "ok"
        assert r.data["dry_run"] is True
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["action_kind"] == "console.run_runbook"
        assert entry["dry_run"] is True
        assert entry["mode"] == "shadow"

    def test_unknown_runbook_errors_and_audits(self) -> None:
        tool, _, store = _build_run_tool()
        r = tool.call(
            arguments={"name": "does-not-exist"},
            principal=_principal(),
        )
        assert r.status == "error"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["error_kind"] == "not_found"

    def test_dry_run_reports_failed_result_as_error(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register(
            "flaky",
            lambda params, dry_run: RunbookResult(ok=False, summary="plan failed"),
        )
        tool, _, store = _build_run_tool(reg)
        r = tool.call(arguments={"name": "flaky"}, principal=_principal())
        assert r.status == "error"
        assert r.data["summary"] == "plan failed"

    def test_registry_raises_runbook_error(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register(
            "x",
            lambda params, dry_run: (_ for _ in ()).throw(RunbookExecutionError("x", "boom")),
        )
        tool, _, store = _build_run_tool(reg)
        r = tool.call(arguments={"name": "x"}, principal=_principal())
        assert r.status == "error"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["error_kind"] == "execution"

    def test_generic_exception_from_adapter_wrapped_as_execution_error(
        self,
    ) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register(
            "boomer",
            lambda params, dry_run: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        tool, _, store = _build_run_tool(reg)
        r = tool.call(arguments={"name": "boomer"}, principal=_principal())
        assert r.status == "error"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["error_kind"] == "execution"

    def test_registry_race_notfound_after_names_check(self) -> None:
        """names() sees the runbook but execute() raises NotFound - race."""
        reg = InMemoryRunbookRegistry()
        reg.register(
            "vanishes",
            lambda params, dry_run: RunbookResult(ok=True, summary="never-called"),
        )
        # Force execute() to raise NotFound on the very next call.
        from aiopspilot.shared.providers.runbook_registry import RunbookNotFoundError

        reg.next_error(RunbookNotFoundError("vanishes"))
        tool, _, store = _build_run_tool(reg)
        r = tool.call(arguments={"name": "vanishes"}, principal=_principal())
        assert r.status == "error"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["error_kind"] == "not_found"
        assert "disappeared" in r.preview


class TestRunRunbookLive:
    def test_live_refused_when_caller_not_owner(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register(
            "prod",
            lambda params, dry_run: RunbookResult(ok=True, summary="ok"),
        )
        tool, _, store = _build_run_tool(reg)
        r = tool.call(
            arguments={"name": "prod", "dry_run": False},
            principal=_principal(role=Role.CONTRIBUTOR),
        )
        assert r.status == "error"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["error_kind"] == "rbac_below_owner_for_live"
        # Runbook was NEVER invoked.
        assert reg.invocations == ()

    def test_live_ok_when_owner(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register(
            "prod",
            lambda params, dry_run: RunbookResult(ok=True, summary="did it"),
        )
        tool, _, store = _build_run_tool(reg)
        r = tool.call(
            arguments={"name": "prod", "dry_run": False},
            principal=_principal(role=Role.OWNER, oid="owner-oid"),
        )
        assert r.status == "ok"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["dry_run"] is False
        assert entry["mode"] == "enforce"
        assert reg.invocations[0] == ("prod", {}, False)

    def test_live_refused_when_approver_not_owner(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register("x", lambda p, d: RunbookResult(ok=True, summary="ok"))
        tool, _, _ = _build_run_tool(reg)
        r = tool.call(
            arguments={"name": "x", "dry_run": False},
            principal=_principal(role=Role.APPROVER),
        )
        assert r.status == "error"


# ---------------------------------------------------------------------------
# ActivateBreakGlassTool - protocol + argument shape
# ---------------------------------------------------------------------------


def _build_bg_tool(
    *,
    pager: InMemoryBreakGlassPager | None = None,
    fixed_now: datetime | None = None,
    max_ttl: int = 14400,
) -> tuple[ActivateBreakGlassTool, InMemoryBreakGlassPager, InMemoryStateStore]:
    pg = pager if pager is not None else InMemoryBreakGlassPager()
    store = InMemoryStateStore()
    clock = (lambda: fixed_now) if fixed_now is not None else None
    tool = ActivateBreakGlassTool(
        pager=pg,
        audit_writer=AuditWriter(audit_store=store),
        max_ttl_seconds=max_ttl,
        clock=clock,
    )
    return tool, pg, store


class TestBreakGlassProtocol:
    def test_satisfies_protocol(self) -> None:
        tool, _, _ = _build_bg_tool()
        assert isinstance(tool, SystemConsoleTool)

    def test_rbac_floor_is_reader(self) -> None:
        tool, _, _ = _build_bg_tool()
        assert tool.rbac_floor is Role.READER

    def test_side_effect_class_is_breakglass(self) -> None:
        tool, _, _ = _build_bg_tool()
        assert tool.side_effect_class == "breakglass"

    def test_ctor_rejects_ttl_above_ceiling(self) -> None:
        with pytest.raises(ValueError, match="ceiling"):
            ActivateBreakGlassTool(
                pager=InMemoryBreakGlassPager(),
                audit_writer=AuditWriter(audit_store=InMemoryStateStore()),
                max_ttl_seconds=99999,
            )

    def test_ctor_rejects_ttl_below_minimum(self) -> None:
        with pytest.raises(ValueError, match="at least 60"):
            ActivateBreakGlassTool(
                pager=InMemoryBreakGlassPager(),
                audit_writer=AuditWriter(audit_store=InMemoryStateStore()),
                max_ttl_seconds=10,
            )

    def test_ctor_rejects_zero_min_reason_length(self) -> None:
        with pytest.raises(ValueError, match="min_reason_length"):
            ActivateBreakGlassTool(
                pager=InMemoryBreakGlassPager(),
                audit_writer=AuditWriter(audit_store=InMemoryStateStore()),
                min_reason_length=0,
            )

    def test_redact_secrets_short_circuits_on_empty(self) -> None:
        """The redaction helper returns empty text unchanged (never
        constructs a spurious REDACTED line for zero input)."""
        from aiopspilot.core.conversation.write_tools import _redact_secrets

        assert _redact_secrets("") == ""


class TestBreakGlassArguments:
    def test_short_reason_refused_and_audited(self) -> None:
        tool, _, store = _build_bg_tool()
        r = tool.call(
            arguments={"reason": "too short", "expiry_seconds": 3600},
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["refusal_kind"] == "short_reason"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["refusal_kind"] == "short_reason"

    def test_expiry_below_minimum_refused(self) -> None:
        tool, _, store = _build_bg_tool()
        r = tool.call(
            arguments={
                "reason": "database down and paging owners now for restore",
                "expiry_seconds": 10,
            },
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["refusal_kind"] == "expiry_below_minimum"

    def test_expiry_above_ceiling_refused(self) -> None:
        tool, _, store = _build_bg_tool()
        r = tool.call(
            arguments={
                "reason": "database down and paging owners now for restore",
                "expiry_seconds": 999999,
            },
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["refusal_kind"] == "expiry_above_ceiling"

    def test_non_integer_expiry_refused(self) -> None:
        tool, _, _ = _build_bg_tool()
        r = tool.call(
            arguments={
                "reason": "database down and paging owners now for restore",
                "expiry_seconds": "not-an-int",
            },
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["refusal_kind"] == "invalid_expiry"

    def test_secret_pattern_in_reason_is_redacted(self) -> None:
        tool, pager, store = _build_bg_tool()
        secret_reason = (
            "prod down; AccountKey=abc123secretkey pasted here for context "
            "and we need to page owners now"
        )
        r = tool.call(
            arguments={"reason": secret_reason, "expiry_seconds": 3600},
            principal=_principal(),
        )
        assert r.status == "ok"
        entry = _unwrap(list(store.audit_entries)[0])
        # Audit never quotes the secret; the redaction placeholder is
        # in its place.
        assert "AccountKey=abc123secretkey" not in entry["reason"]
        assert "[REDACTED-SUSPECTED-SECRET]" in entry["reason"]
        # Pager receives the same redacted reason.
        call = pager.calls[0]
        assert "AccountKey=abc123secretkey" not in str(call["reason_redacted"])


class TestBreakGlassHappyPath:
    def test_grant_records_pager_receipt(self) -> None:
        fixed_now = datetime(2026, 7, 7, 10, 0, 0, tzinfo=UTC)
        tool, pager, store = _build_bg_tool(fixed_now=fixed_now)
        r = tool.call(
            arguments={
                "reason": "database primary unreachable, need to elevate",
                "expiry_seconds": 3600,
            },
            principal=_principal(),
        )
        assert r.status == "ok"
        assert r.data["pager_receipt"].startswith("pager-")
        assert r.data["activated_at"] == fixed_now.isoformat()
        expected_expiry = (fixed_now + timedelta(seconds=3600)).isoformat()
        assert r.data["expires_at"] == expected_expiry
        # Pager saw exactly one call.
        assert len(pager.calls) == 1
        # Audit trail has exactly one entry.
        entries = list(store.audit_entries)
        assert len(entries) == 1
        entry = _unwrap(entries[0])
        assert entry["decision"] == "ok"
        assert entry["pager_receipt"] == r.data["pager_receipt"]

    def test_evidence_refs_include_audit_and_pager(self) -> None:
        tool, _, _ = _build_bg_tool()
        r = tool.call(
            arguments={
                "reason": "primary db down, page on-call owner now please",
                "expiry_seconds": 3600,
            },
            principal=_principal(),
        )
        assert any(ref.startswith("audit:") for ref in r.evidence_refs)
        assert any(ref.startswith("pager:") for ref in r.evidence_refs)


class TestBreakGlassPagerFailure:
    def test_no_channel_configured_refuses_grant(self) -> None:
        pager = InMemoryBreakGlassPager(configured=False)
        tool, _, store = _build_bg_tool(pager=pager)
        r = tool.call(
            arguments={
                "reason": "primary db down, need to elevate right now please",
                "expiry_seconds": 3600,
            },
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["refusal_kind"] == "pager_no_channel"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["refusal_kind"] == "pager_no_channel"
        assert entry["pager_receipt"] == ""

    def test_delivery_failure_refuses_grant(self) -> None:
        pager = InMemoryBreakGlassPager()
        pager.next_error(BreakGlassDeliveryError("all channels timed out"))
        tool, _, store = _build_bg_tool(pager=pager)
        r = tool.call(
            arguments={
                "reason": "primary db down, need to elevate right now please",
                "expiry_seconds": 3600,
            },
            principal=_principal(),
        )
        assert r.status == "error"
        assert r.data["refusal_kind"] == "pager_delivery"
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["decision"] == "error"


# ---------------------------------------------------------------------------
# Provider fake sanity - InMemoryRunbookRegistry / InMemoryBreakGlassPager
# ---------------------------------------------------------------------------


class TestFakeContract:
    @pytest.mark.asyncio
    async def test_runbook_registry_names_are_sorted(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register("b", lambda p, d: RunbookResult(ok=True, summary="ok"))
        reg.register("a", lambda p, d: RunbookResult(ok=True, summary="ok"))
        assert reg.names() == ("a", "b")

    def test_runbook_registry_rejects_empty_name(self) -> None:
        reg = InMemoryRunbookRegistry()
        with pytest.raises(ValueError, match="non-empty"):
            reg.register("", lambda p, d: RunbookResult(ok=True, summary="ok"))

    @pytest.mark.asyncio
    async def test_runbook_registry_records_invocations(self) -> None:
        reg = InMemoryRunbookRegistry()
        reg.register("x", lambda p, d: RunbookResult(ok=True, summary="ok"))
        await reg.execute(name="x", params={"k": 1}, dry_run=True)
        assert reg.invocations == (("x", {"k": 1}, True),)

    @pytest.mark.asyncio
    async def test_break_glass_pager_defaults_to_configured(self) -> None:
        pager = InMemoryBreakGlassPager()
        receipt = await pager.notify_owners(
            actor_oid="a",
            actor_display="A",
            reason_redacted="r",
            activated_at=datetime.now(tz=UTC),
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )
        assert receipt.startswith("pager-")

    @pytest.mark.asyncio
    async def test_break_glass_pager_no_channel_raises(self) -> None:
        pager = InMemoryBreakGlassPager(configured=False)
        with pytest.raises(BreakGlassNoChannelError):
            await pager.notify_owners(
                actor_oid="a",
                actor_display="A",
                reason_redacted="r",
                activated_at=datetime.now(tz=UTC),
                expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            )
