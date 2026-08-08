"""SLO registry - load YAML SLO definitions from a catalog directory.

The catalog is fork-hosted: upstream ships **zero** SLOs
(:doc:`scope-expansion § 3.3 <../../../../docs/roadmap/fork-and-sequencing/scope-expansion.md>`).
A fork drops ``<slo-id>.yaml`` files under ``rule-catalog/slo/`` and
the composition root binds a registry pointing at that directory.

Every file is validated against ``shared/contracts/slo/schema.json``
before construction so a malformed YAML fails fast at load, not at
alert time.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

from .models import SLI, SLO, BurnRateAlertDef, SLIKind


class SloRegistryError(ValueError):
    """Raised on schema violation or duplicate id at load."""


class SloRegistry:
    """Loaded set of :class:`SLO` objects, indexed by id."""

    def __init__(self, *, slos: Iterable[SLO]) -> None:
        self._by_id: dict[str, SLO] = {}
        for slo in slos:
            if slo.id in self._by_id:
                raise SloRegistryError(f"duplicate SLO id {slo.id!r}")
            self._by_id[slo.id] = slo

    def get(self, slo_id: str) -> SLO | None:
        return self._by_id.get(slo_id)

    def all(self) -> tuple[SLO, ...]:
        return tuple(self._by_id.values())

    @classmethod
    def from_directory(cls, root: Path | str) -> SloRegistry:
        """Load every ``*.yaml`` under ``root`` and return a registry.

        ``root`` may be missing (returns an empty registry) - the
        upstream ships no SLOs by design.
        """
        base = Path(root)
        slos: list[SLO] = []
        if not base.is_dir():
            return cls(slos=slos)
        validator = _schema_validator()
        for path in sorted(base.rglob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if data is None:
                continue
            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            if errors:
                first = errors[0]
                where = ".".join(str(p) for p in first.absolute_path) or "<root>"
                raise SloRegistryError(f"{path}: {where}: {first.message}")
            slos.append(_slo_from_dict(data))
        return cls(slos=slos)


def _schema_validator() -> Draft202012Validator:
    schema_raw = PackageResourceSchemaRegistry().get("slo")
    return Draft202012Validator(dict(schema_raw))


def _slo_from_dict(data: Mapping[str, Any]) -> SLO:
    sli_raw = data["sli"]
    sli = SLI(
        kind=SLIKind(sli_raw["kind"]),
        good_query=sli_raw["good_query"],
        total_query=sli_raw["total_query"],
        labels=dict(sli_raw.get("labels") or {}),
    )
    alerts = tuple(
        BurnRateAlertDef(
            name=a["name"],
            short_window_minutes=a["short_window_minutes"],
            long_window_minutes=a["long_window_minutes"],
            burn_rate_threshold=a["burn_rate_threshold"],
            severity=a.get("severity", "sev3"),
        )
        for a in (data.get("burn_rate_alerts") or [])
    )
    return SLO(
        id=data["id"],
        objective_ratio=data["objective_ratio"],
        window_days=data["window_days"],
        sli=sli,
        burn_rate_alerts=alerts,
        description=data.get("description"),
        schema_version=data["schema_version"],
    )


# ``json`` is imported for the validator's error formatting even
# though not directly used above; keeps future error-serialisation
# additions typo-free.
_ = json


__all__ = ["SloRegistry", "SloRegistryError"]
