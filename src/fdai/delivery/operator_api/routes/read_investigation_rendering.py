"""Deterministic answer rendering for Heimdall read investigations."""

from __future__ import annotations

from datetime import UTC
from typing import assert_never

from fdai.shared.providers.read_investigation import (
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ReadInvestigationIntent,
)


def _render_answer(
    *,
    resource_name: str,
    intent: ReadInvestigationIntent,
    outcome: str,
    evidence: tuple[ReadEvidenceEnvelope, ...],
    korean: bool,
    latest_change_only: bool,
    explain_read_availability: bool,
) -> str:
    records = tuple(record for envelope in evidence for record in envelope.records)
    if explain_read_availability:
        authorities = tuple(dict.fromkeys(envelope.authority for envelope in evidence))
        authority_label = ", ".join(authorities) if authorities else "resource resolution"
        states = tuple(
            dict.fromkeys(record.state for record in records if record.state is not None)
        )
        state_label = ", ".join(states) if states else "no state record"
        if outcome == "matched":
            if korean:
                return (
                    f"{resource_name}의 Azure 제어 평면 상태는 읽을 수 있습니다: {state_label}. "
                    "이 상태 조회에서는 범위 또는 권한 실패가 발생하지 않았습니다. 게스트 운영 "
                    "체제 내부 이벤트는 별도의 guest log 근거가 필요합니다."
                )
            return (
                f"The Azure control-plane state for {resource_name} is readable: "
                f"{state_label}. This state read did not encounter a scope or authorization "
                "failure. Guest operating-system events require separate guest-log evidence."
            )
        if outcome == "none":
            if korean:
                return (
                    f"{resource_name}의 {authority_label} 조회는 완료했지만 상태 레코드를 찾지 "
                    "못했습니다. 이는 관찰 범위의 근거 공백이며 권한 거부를 증명하지는 "
                    "않습니다. 게스트 운영 체제 이벤트는 별도의 guest log 근거가 필요합니다."
                )
            return (
                f"The {authority_label} query for {resource_name} completed but returned no "
                "state record. This is an evidence gap in the observed scope, not proof of an "
                "authorization denial. Guest operating-system events require separate guest-log "
                "evidence."
            )
        if korean:
            return (
                f"{resource_name}의 상태 조회를 완료하지 못했습니다. 확인 불가능한 근거 범위는 "
                f"{authority_label}입니다. 서버가 허용한 범위 밖이거나 reader/provider 권한을 "
                "사용할 수 없는 경우이며, 이 결과만으로 둘 중 하나를 추측하지 않습니다."
            )
        return (
            f"The state read for {resource_name} was unavailable at {authority_label}. The "
            "resource can be outside the server-owned scope, or reader/provider authorization "
            "can be unavailable; this result does not guess between those causes."
        )
    if intent is ReadInvestigationIntent.RESOURCE_STATE:
        if records:
            latest = max(records, key=lambda record: record.occurred_at)
            observed = latest.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            state = latest.state or latest.status
            return (
                f"{resource_name}의 관찰된 상태는 {state}이며 관찰 시각은 {observed}입니다."
                if korean
                else f"The observed state of {resource_name} is {state} at {observed}."
            )
        return (
            f"{resource_name}의 현재 상태를 확인할 evidence가 없습니다."
            if korean
            else f"No evidence is available to confirm the current state of {resource_name}."
        )
    if intent is ReadInvestigationIntent.PLATFORM_HEALTH:
        if records:
            latest = max(records, key=lambda record: record.occurred_at)
            observed = latest.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            health = latest.health_kind or latest.state or latest.status
            return (
                f"{resource_name}의 관찰된 플랫폼 상태는 {health}이며 관찰 시각은 {observed}입니다."
                if korean
                else f"The observed platform health of {resource_name} is {health} at {observed}."
            )
        return (
            f"{resource_name}의 플랫폼 상태를 확인할 evidence가 없습니다."
            if korean
            else f"No evidence is available to confirm platform health for {resource_name}."
        )
    if intent is ReadInvestigationIntent.GUEST_SHUTDOWN:
        shutdowns = sorted(
            (
                record
                for record in records
                if record.operation_kind in {"shutdown", "power_off", "guest_shutdown"}
            ),
            key=lambda record: record.occurred_at,
            reverse=True,
        )
        if shutdowns:
            latest = shutdowns[0]
            observed = latest.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            return (
                f"{resource_name}의 guest OS 종료 evidence가 {observed}에 관찰되었습니다."
                if korean
                else f"Guest OS shutdown evidence for {resource_name} was observed at {observed}."
            )
        return (
            f"구성된 guest log에서 {resource_name}의 OS 종료 evidence를 찾지 못했습니다."
            if korean
            else f"No OS shutdown evidence for {resource_name} was found in configured guest logs."
        )
    if intent is ReadInvestigationIntent.NETWORK_SECURITY:
        if not records:
            return (
                f"{resource_name}의 NSG 구성 evidence가 없습니다."
                if korean
                else f"No NSG configuration evidence is available for {resource_name}."
            )
        allowed = [
            record
            for record in records
            if record.status.casefold() == "allow"
            and dict(record.details).get("direction", "").casefold() == "inbound"
        ]
        if not allowed:
            return (
                f"{resource_name}에서 확인된 inbound 허용 규칙이 없습니다."
                if korean
                else f"No inbound allow rules were observed for {resource_name}."
            )
        rendered = "; ".join(_render_nsg_rule(record.details) for record in allowed)
        caveat = (
            " 이 결과는 NSG 구성 규칙이며 end-to-end 도달 가능성을 단독으로 증명하지 않습니다."
            if korean
            else " These are configured NSG rules and do not alone prove end-to-end reachability."
        )
        prefix = "확인된 inbound 허용 규칙" if korean else "observed inbound allow rules"
        return f"{resource_name} {prefix}: {rendered}.{caveat}"
    if intent is ReadInvestigationIntent.NETWORK_PEERING:
        if not records:
            return (
                f"{resource_name}의 VNet peering evidence가 없습니다."
                if korean
                else f"No VNet peering evidence is available for {resource_name}."
            )
        rendered = "; ".join(_render_peering(record.details, record.status) for record in records)
        caveat = (
            " 반대편 VNet과 effective route를 확인하지 않은 연결은 단방향 증거입니다."
            if korean
            else (
                " A connection not verified from the remote VNet and effective routes "
                "is one-sided evidence."
            )
        )
        prefix = "피어링" if korean else "peerings"
        return f"{resource_name} {prefix}: {rendered}.{caveat}"
    if intent is ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY and latest_change_only:
        successful_changes = sorted(
            (
                record
                for record in records
                if record.status == "succeeded" and record.operation_kind is not None
            ),
            key=lambda record: record.occurred_at,
            reverse=True,
        )
        if successful_changes:
            latest = successful_changes[0]
            observed = latest.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
            operation = latest.operation_kind or "unknown"
            actor = (
                f"{latest.actor_kind.value} ({latest.actor_ref})"
                if latest.actor_kind is not None and latest.actor_ref is not None
                else None
            )
            if korean:
                actor_label = actor or "Activity Log에서 확인되지 않은 주체"
                return (
                    f"{resource_name}의 가장 최근 성공한 변경은 {observed}의 {operation}입니다. "
                    f"호출 주체는 {actor_label}입니다."
                )
            actor_label = actor or "a caller not present in the Activity Log evidence"
            return (
                f"The most recent successful change for {resource_name} was {operation} at "
                f"{observed}. The caller was {actor_label}."
            )
        return (
            f"최근 30일 Azure Activity Log에서 {resource_name}의 성공한 변경을 찾지 못했습니다."
            if korean
            else (
                f"No successful change for {resource_name} was found in the last 30 days of "
                "Azure Activity Log."
            )
        )
    if intent is ReadInvestigationIntent.CHANGE_ATTRIBUTION:
        return _render_stop_history(resource_name=resource_name, records=records, korean=korean)
    if intent is ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY:
        return _render_stop_history(resource_name=resource_name, records=records, korean=korean)
    assert_never(intent)


def _render_stop_history(
    *,
    resource_name: str,
    records: tuple[ReadEvidenceRecord, ...],
    korean: bool,
) -> str:
    successful_stops = sorted(
        (
            record
            for record in records
            if record.status == "succeeded"
            and record.operation_kind in {"stop", "deallocate", "power_off"}
        ),
        key=lambda record: record.occurred_at,
        reverse=True,
    )
    if successful_stops:
        latest = successful_stops[0]
        observed = latest.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        operation = latest.operation_kind or "stop"
        actor = (
            f"{latest.actor_kind.value} ({latest.actor_ref})"
            if latest.actor_kind is not None and latest.actor_ref is not None
            else None
        )
        if korean:
            actor_sentence = (
                f" 호출 주체는 {actor}입니다."
                if actor is not None
                else " 호출 주체는 Activity Log에서 확인되지 않았습니다."
            )
            return (
                f"{resource_name}의 최근 성공한 중지 작업은 {observed}에 Azure Activity Log에 "
                f"기록되었습니다. 작업 종류는 {operation}입니다.{actor_sentence} "
                "현재 중지 상태는 적어도 이 "
                "시점부터 이어진 것으로 확인됩니다."
            )
        actor_sentence = (
            f" The caller was {actor}."
            if actor is not None
            else " The caller was not present in the Activity Log evidence."
        )
        return (
            f"The latest successful stop for {resource_name} was recorded in Azure Activity "
            f"Log at {observed}. The operation was {operation}.{actor_sentence} "
            "The current stopped state is "
            "confirmed from at least that time."
        )
    if korean:
        return (
            f"최근 30일 Azure Activity Log에서 {resource_name}의 성공한 중지 작업을 "
            "찾지 못해 시작 시각을 확정할 수 없습니다."
        )
    return (
        f"No successful stop operation for {resource_name} was found in the last 30 days of "
        "Azure Activity Log, so the start time is unconfirmed."
    )


def _render_nsg_rule(details: tuple[tuple[str, str], ...]) -> str:
    values = dict(details)
    return (
        f"{values.get('protocol', 'unknown').upper()} "
        f"{values.get('destination_ports', 'unknown')} from "
        f"{values.get('source_prefixes', 'unknown')} "
        f"(priority {values.get('priority', 'unknown')}, "
        f"rule {values.get('rule_name', 'unknown')})"
    )


def _render_peering(details: tuple[tuple[str, str], ...], status: str) -> str:
    values = dict(details)
    return (
        f"{values.get('peering_name', 'unknown')} -> {values.get('remote_vnet', 'unknown')} "
        f"[{status}, sync={values.get('sync_level', 'unknown')}, "
        f"access={values.get('allow_vnet_access', 'unknown')}, "
        f"forwarded={values.get('allow_forwarded_traffic', 'unknown')}, "
        f"gateway-transit={values.get('allow_gateway_transit', 'unknown')}, "
        f"remote-gateway={values.get('use_remote_gateways', 'unknown')}]"
    )


def _is_korean(value: str) -> bool:
    return any("가" <= character <= "힣" for character in value)
