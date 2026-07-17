#!/usr/bin/env python3
"""Ingest a bounded Kubernetes documentation scenario batch.

The source class is Kubernetes official operational documentation, licensed
CC BY 4.0. FDAI stores no copied prose: each curated mapping records only the
public URL, section locator, and review date. Extraction is deterministic and
network-free; a source watcher can later compare the locator upstream without
making catalog generation depend on network availability.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import yaml

from fdai.core.detection.signals import SignalRole, known_signals

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_OUT_DIR = _REPO_ROOT / "rule-catalog" / "chaos-scenarios" / "collected" / "kubernetes-docs"
_SOURCE_PREFIX = "https://kubernetes.io/docs/"
_SOURCE_LICENSE = "CC-BY-4.0"
_REVIEWED_AT = "2026-07-17"


@dataclass(frozen=True, slots=True)
class Entry:
    slug: str
    source_url: str
    source_section: str
    category: str
    target_type: str
    fault_family: str
    intensity: str
    expected_signal: str
    description: str
    rollback_note: str


_ENTRIES = (
    Entry(
        slug="pod-disruption-budget-gap",
        source_url="https://kubernetes.io/docs/concepts/workloads/pods/disruptions/",
        source_section="pod-disruption-budgets",
        category="compute",
        target_type="pod",
        fault_family="stop",
        intensity="high",
        expected_signal="backend_health",
        description="Concurrent voluntary disruptions exceed the workload availability budget.",
        rollback_note="Restore healthy replicas and stop additional voluntary disruptions.",
    ),
    Entry(
        slug="dns-resolution-failure",
        source_url="https://kubernetes.io/docs/tasks/administer-cluster/dns-debugging-resolution/",
        source_section="check-the-local-dns-configuration-first",
        category="network",
        target_type="dns",
        fault_family="misroute",
        intensity="high",
        expected_signal="request_failure",
        description="Workload DNS configuration prevents service-name resolution.",
        rollback_note="Restore the prior resolver configuration and verify service lookup.",
    ),
    Entry(
        slug="image-pull-backoff",
        source_url="https://kubernetes.io/docs/concepts/containers/images/#imagepullbackoff",
        source_section="imagepullbackoff",
        category="dependency",
        target_type="pod",
        fault_family="deny",
        intensity="high",
        expected_signal="rollout_stall",
        description="A workload cannot pull its declared image and the rollout stalls.",
        rollback_note="Restore the previous resolvable image reference and restart the rollout.",
    ),
)


def _validate_entry(entry: Entry) -> None:
    if not entry.source_url.startswith(_SOURCE_PREFIX):
        raise ValueError("unsupported_source_url")
    if not entry.source_section:
        raise ValueError("missing_source_section")
    signal = known_signals().get(entry.expected_signal)
    if signal is None:
        raise ValueError("unknown_expected_signal")
    if signal.role is SignalRole.RCA_ONLY:
        raise ValueError("rca_only_signal_not_scenario_eligible")


def _to_body(entry: Entry) -> dict[str, object]:
    _validate_entry(entry)
    return {
        "id": f"chaos.kubernetes-docs.{entry.slug}",
        "version": 1,
        "provenance": {
            "source": "vendor-doc",
            "source_url": entry.source_url,
            "source_ref": (
                f"section={entry.source_section};license={_SOURCE_LICENSE};reviewed={_REVIEWED_AT}"
            ),
            "synthesis_method": "manual",
        },
        "category": entry.category,
        "target_type": entry.target_type,
        "fault_family": entry.fault_family,
        "intensity": entry.intensity,
        "duration_seconds": 360,
        "expected_signal": entry.expected_signal,
        "injector": "needs-injector",
        "blast_radius_cap": 1,
        "rollback_note": entry.rollback_note,
        "gates": {"shadow_status": "pending", "enforce_status": None},
        "requires_hardware": False,
        "description": entry.description,
        "tags": ["kubernetes", "vendor-doc"],
    }


def main() -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    valid_names = {f"{entry.slug}.yaml" for entry in _ENTRIES}
    for existing in _OUT_DIR.glob("*.yaml"):
        if existing.name not in valid_names:
            existing.unlink()
    for entry in _ENTRIES:
        path = _OUT_DIR / f"{entry.slug}.yaml"
        path.write_text(yaml.safe_dump(_to_body(entry), sort_keys=False))
    print(f"wrote {len(_ENTRIES)} Kubernetes docs scenarios -> {_OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
