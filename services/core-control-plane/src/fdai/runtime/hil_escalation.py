"""Compose catalog timing and current-role checks without promoting HIL escalation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import yaml

from fdai.core.hil_resume.escalation_catalog_binding import CatalogEscalationTiming
from fdai.core.hil_resume.rung_eligibility import DirectoryRungEligibility
from fdai.core.rbac.resolver import GroupMapping
from fdai.core.rbac.roles import Role
from fdai.delivery.identity.entra_directory import EntraHumanIdentityDirectory
from fdai.rule_catalog.schema.escalation_ladder import load_escalation_catalog
from fdai.shared.providers.workload_identity import WorkloadIdentity


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


__all__ = ["build_escalation_timing", "build_rung_eligibility"]
