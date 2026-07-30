from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai.delivery.read_api.routes.chat_t2_recovery import (
    T2RecoveryChatTools,
    needs_t2_recovery_evidence,
)
from fdai.delivery.read_api.routes.chat_verification import verify_answer


class _Reader:
    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.records = records
        self.calls: list[tuple[str, int]] = []

    async def read_states(self, prefix: str, *, limit: int) -> Sequence[Mapping[str, Any]]:
        self.calls.append((prefix, limit))
        return self.records


class _Fallback:
    def __init__(self) -> None:
        self.principal_id: str | None = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any]:
        self.principal_id = principal_id
        return {"tool": "fallback", "result": {"prompt": prompt}}


def _receipt(
    *,
    receipt_id: str,
    status: str,
    terminal: bool,
    recovered: bool,
    route_ref: str = "primary",
) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "correlation_id": "corr-1",
        "status": status,
        "terminal": terminal,
        "recovered": recovered,
        "route_ref": route_ref,
        "failure_class": "transient" if status == "failed" else None,
        "observed_at": "2026-08-13T00:00:00Z",
    }


def test_recognizes_t2_proposer_failure_questions() -> None:
    assert needs_t2_recovery_evidence("T2 proposer error:DeploymentNotFound")
    assert needs_t2_recovery_evidence("T2 제안 오류는 왜 발생했어?")
    assert not needs_t2_recovery_evidence("현재 인벤토리를 보여줘")


async def test_projects_recovered_attempts_and_verifier_replaces_provisional() -> None:
    reader = _Reader(
        (
            _receipt(
                receipt_id="receipt-2",
                status="succeeded",
                terminal=False,
                recovered=True,
                route_ref="secondary",
            ),
            _receipt(
                receipt_id="receipt-1",
                status="failed",
                terminal=False,
                recovered=False,
            ),
        )
    )
    evidence = await T2RecoveryChatTools(reader).resolve(
        "T2 proposer error:DeploymentNotFound 원인이 뭐야?",
        principal_id="operator-1",
    )

    assert evidence is not None
    assert reader.calls == [("t2-recovery:receipt:", 100)]
    assert evidence["result"]["recovery_state"] == "recovered"
    assert evidence["result"]["attempt_count"] == 2

    verified = verify_answer(
        "unsupported provisional answer",
        {"_tool_evidence": evidence},
        locale="ko",
    )
    assert verified.status == "corrected"
    assert verified.authority == "server_t2_recovery_ledger"
    assert verified.reason_code == "t2_recovery_grounded"
    assert verified.evidence_refs == (
        "t2-recovery:receipt-2",
        "t2-recovery:receipt-1",
    )
    assert "recovered" in verified.answer
    assert "시도 2개" in verified.answer


async def test_projects_terminal_failure_and_legacy_detail_boundary() -> None:
    reader = _Reader(
        (
            _receipt(
                receipt_id="legacy-event-1",
                status="failed",
                terminal=True,
                recovered=False,
                route_ref="legacy",
            ),
        )
    )

    evidence = await T2RecoveryChatTools(reader).resolve(
        "T2 proposer failure status",
        principal_id="operator-1",
    )

    assert evidence is not None
    assert evidence["result"]["recovery_state"] == "unavailable"
    assert evidence["result"]["legacy_detail_unavailable"] is True
    verified = verify_answer("draft", {"_tool_evidence": evidence}, locale="en")
    assert "original provider error detail is unavailable" in verified.answer


async def test_delegates_unrelated_prompt_with_original_principal() -> None:
    fallback = _Fallback()
    evidence = await T2RecoveryChatTools(_Reader(()), fallback=fallback).resolve(
        "show inventory",
        principal_id="operator-7",
    )

    assert evidence == {"tool": "fallback", "result": {"prompt": "show inventory"}}
    assert fallback.principal_id == "operator-7"


async def test_returns_grounded_no_observation_answer() -> None:
    evidence = await T2RecoveryChatTools(_Reader(())).resolve(
        "T2 proposer recovery status",
        principal_id="operator-1",
    )

    assert evidence is not None
    verified = verify_answer("draft", {"_tool_evidence": evidence}, locale="en")
    assert verified.status == "corrected"
    assert verified.reason_code == "t2_recovery_not_observed"
    assert verified.checks_total == 0
    assert "No retained T2 proposer" in verified.answer
