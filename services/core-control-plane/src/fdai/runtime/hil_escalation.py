"""Compose catalog timing and current-role checks without promoting HIL escalation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
import yaml

from fdai.core.hil_resume.escalation_catalog_binding import CatalogEscalationTiming
from fdai.core.hil_resume.escalation_supervisor import (
    EscalationPolicy,
    EscalationRung,
    HumanNonResponseSupervisor,
)
from fdai.core.hil_resume.forecast_urgency import ForecastUrgencyReader
from fdai.core.hil_resume.load_control import (
    ApprovalLoadController,
    ApprovalLoadPolicy,
    ApprovalReminderDispatcher,
)
from fdai.core.hil_resume.rung_eligibility import DirectoryRungEligibility
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.rbac.roles import Role
from fdai.delivery.identity.entra_directory import EntraHumanIdentityDirectory
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_forecast_urgency import PostgresForecastUrgencyReader
from fdai.rule_catalog.schema.escalation_ladder import load_escalation_catalog
from fdai.runtime.report_lines import ReportLineRuntime, build_report_line_runtime
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.hil_channel import HilChannel
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity


@dataclass(frozen=True, slots=True)
class HilRuntimeSupport:
    """HIL routing services composed without execution authority."""

    report_lines: ReportLineRuntime | None
    escalation: HumanNonResponseSupervisor | None
    load_controller: ApprovalLoadController | None
    reminder_dispatcher: ApprovalReminderDispatcher | None


def build_hil_runtime_support(
    *,
    catalog_root: Path,
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    store: StateStore,
    channel: HilChannel | None,
    load_policy: ApprovalLoadPolicy | None,
    escalation_rungs: tuple[EscalationRung, ...],
) -> HilRuntimeSupport:
    """Compose report-line routing, escalation, and approval load control."""

    rung_eligibility = build_rung_eligibility(
        catalog_root,
        http_client=http_client,
        identity=identity,
        environment=environment,
    )
    report_lines = build_report_line_runtime(
        store=store,
        environment=environment,
        role_eligibility=rung_eligibility,
    )
    if report_lines is not None and channel is None:
        raise ValueError("report-line approval routing requires a configured HIL channel")
    escalation = (
        HumanNonResponseSupervisor(
            state_store=store,
            channel=channel,
            catalog_timing=build_escalation_timing(catalog_root, environment),
            forecast_urgency_reader=build_forecast_urgency_reader(environment),
            eligibility=(
                report_lines.escalation_eligibility
                if report_lines is not None
                else rung_eligibility
            ),
            policy=EscalationPolicy(
                decision_timeout_seconds=300,
                overall_timeout_seconds=1800,
                mode=Mode.SHADOW,
            ),
        )
        if channel is not None and (escalation_rungs or report_lines is not None)
        else None
    )

    async def observe_delivery(approval_id: str, delivered_at: datetime) -> None:
        if escalation is not None:
            await escalation.mark_delivered(approval_id, at=delivered_at)

    load_controller = (
        ApprovalLoadController(state_store=store, policy=load_policy)
        if channel is not None and load_policy is not None
        else None
    )
    reminder_dispatcher = (
        ApprovalReminderDispatcher(
            state_store=store,
            channel=channel,
            policy=load_policy,
            delivery_observer=observe_delivery if escalation is not None else None,
        )
        if channel is not None and load_policy is not None
        else None
    )
    return HilRuntimeSupport(
        report_lines=report_lines,
        escalation=escalation,
        load_controller=load_controller,
        reminder_dispatcher=reminder_dispatcher,
    )


def build_escalation_timing(
    catalog_root: Path, environment: Mapping[str, str]
) -> CatalogEscalationTiming:
    """Load reviewed catalogs and explicit private audience mappings at startup."""
    catalog = load_escalation_catalog(catalog_root / "escalation-ladders")
    target_environment = environment.get("FDAI_HIL_ESCALATION_ENVIRONMENT", "").strip()
    if target_environment not in {"", "prod", "nonprod"}:
        raise ValueError("HIL escalation environment MUST be prod or nonprod when configured")
    audiences: dict[str, tuple[str, ...]] = {}
    raw = environment.get("FDAI_HIL_ESCALATION_AUDIENCES_JSON", "").strip()
    if raw:
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise ValueError("HIL escalation audiences MUST be valid JSON") from exc
        if not isinstance(decoded, dict) or len(decoded) > 32:
            raise ValueError("HIL escalation audiences MUST be a bounded mapping")
        for name, subjects in decoded.items():
            if (
                not isinstance(name, str)
                or not 1 <= len(name) <= 128
                or not isinstance(subjects, list)
                or len(subjects) != 1
                or not isinstance(subjects[0], str)
                or not subjects[0].strip()
                or len(subjects[0]) > 256
            ):
                raise ValueError("HIL catalog audience requires one explicit bounded human")
            audiences[name] = (subjects[0].strip(),)
    return CatalogEscalationTiming(
        catalog=catalog,
        environment=target_environment or "unavailable",
        audiences=audiences.get if audiences else None,
    )


def build_rung_eligibility(
    catalog_root: Path,
    *,
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
    environment: Mapping[str, str],
) -> DirectoryRungEligibility | None:
    """Reuse the Core read identity and ordinary RBAC map; never acquire the access writer."""
    if http_client is None or identity is None:
        return None
    path = catalog_root.parent / "config/rbac-groups.yaml"
    groups = GroupMapping.from_config(
        yaml.safe_load(path.read_text(encoding="utf-8")), environ=environment
    )
    return DirectoryRungEligibility(
        directory=EntraHumanIdentityDirectory(
            client=http_client, identity=identity, roster_cache_seconds=0
        ),
        role_group_ids={
            role.value: group
            for group, role in groups.as_dict().items()
            if role is not Role.BREAK_GLASS
        },
    )


def build_forecast_urgency_reader(environment: Mapping[str, str]) -> ForecastUrgencyReader | None:
    """Bind the same Core forecast ledger locally and deployed; no in-memory fallback."""
    dsn = environment.get("FDAI_STATE_STORE_DSN", "").strip()
    return PostgresForecastUrgencyReader(PostgresStateStoreConfig(dsn=dsn)) if dsn else None


__all__ = [
    "HilRuntimeSupport",
    "build_escalation_timing",
    "build_forecast_urgency_reader",
    "build_hil_runtime_support",
    "build_rung_eligibility",
]
