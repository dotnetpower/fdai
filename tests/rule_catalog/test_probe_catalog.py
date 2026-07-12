"""Probe catalog loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.rule_catalog.schema.probe import (
    ProbeCatalogError,
    load_probe_catalog,
    probe_ids,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBES_ROOT = _REPO_ROOT / "rule-catalog" / "probes"


def test_shipped_probes_load():
    catalog = load_probe_catalog(_PROBES_ROOT)
    ids = probe_ids(catalog)
    assert {
        "vm_traffic_last_5m",
        "storage_access_log",
        "lb_backend_health",
        "blast_radius_classifier",
    } <= ids


def test_probe_manifest_fields():
    catalog = load_probe_catalog(_PROBES_ROOT)
    vm = next(p for p in catalog if p.id == "vm_traffic_last_5m")
    assert vm.adapter_ref == "probe-adapters/azure-monitor"
    assert vm.timeout_seconds == 5
    assert vm.cache_ttl_seconds == 60
    assert set(vm.interpretation) == {"quiet", "active", "overloaded"}


def test_invalid_probe_raises(tmp_path):
    # Copy the schema so the loader can validate.
    schema_src = _PROBES_ROOT / "probe.schema.json"
    schema_dst = tmp_path / "probe.schema.json"
    schema_dst.write_bytes(schema_src.read_bytes())
    (tmp_path / "bad.yaml").write_text("id: x\n")  # missing required fields
    with pytest.raises(ProbeCatalogError) as exc_info:
        load_probe_catalog(tmp_path)
    # bad.yaml has multiple validation errors; message aggregates them
    assert "bad.yaml" in str(exc_info.value)


def test_missing_root_raises(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError):
        load_probe_catalog(missing)


def test_placeholder_mode_returns_empty(tmp_path):
    """A probe root with no schema file returns an empty tuple.

    This matches the Day-1 contract: rule-catalog/probes/ can exist
    with only README.md before Month 1 lands the schema, and startup
    MUST NOT crash.
    """

    (tmp_path / "README.md").write_text("placeholder\n")
    catalog = load_probe_catalog(tmp_path)
    assert catalog == ()


def test_duplicate_id_rejected(tmp_path):
    schema_src = _PROBES_ROOT / "probe.schema.json"
    (tmp_path / "probe.schema.json").write_bytes(schema_src.read_bytes())
    body = (
        'schema_version: "1.0.0"\n'
        "id: dup_probe\n"
        'description: "test"\n'
        "adapter_ref: probe-adapters/fake\n"
        "interpretation:\n"
        '  quiet: "x < 1"\n'
        '  active: "x < 2"\n'
        '  overloaded: "x >= 2"\n'
        "timeout_seconds: 5\n"
        "cache_ttl_seconds: 60\n"
    )
    (tmp_path / "a.yaml").write_text(body)
    (tmp_path / "b.yaml").write_text(body)
    with pytest.raises(ProbeCatalogError) as exc_info:
        load_probe_catalog(tmp_path)
    assert "duplicate probe id" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Doc-catalog drift-guard (M1.2 starter probes)
# ---------------------------------------------------------------------------

# Locked list from docs/roadmap/fork-and-sequencing/implementation-plan.md § Wave M1 - M1.2.
# Editing either side without the other = merge-blocker.
_M1_2_STARTER_PROBES = frozenset(
    {
        "vm_traffic_last_5m",
        "storage_access_log",
        "lb_backend_health",
        "blast_radius_classifier",
    }
)


def test_every_m1_2_doc_declared_starter_probe_ships_as_yaml() -> None:
    """implementation-plan.md § M1.2 -> shipped YAML: no gap allowed."""
    catalog = load_probe_catalog(_PROBES_ROOT)
    shipped = probe_ids(catalog)
    missing = sorted(_M1_2_STARTER_PROBES - shipped)
    assert not missing, (
        f"implementation-plan.md declares starter probes not shipped as YAML: "
        f"{missing}. Author the probe under rule-catalog/probes/ or update the "
        f"doc."
    )


def test_no_extra_shipped_probe_undocumented() -> None:
    """shipped YAML -> implementation-plan.md § M1.2: no drift the other way.

    Adding a fourth starter probe requires an implementation-plan.md
    edit (and this test update) in the same PR so the docs-first rule
    holds.
    """
    catalog = load_probe_catalog(_PROBES_ROOT)
    shipped = probe_ids(catalog)
    extra = sorted(shipped - _M1_2_STARTER_PROBES)
    assert not extra, (
        f"shipped probe(s) not documented in implementation-plan.md § M1.2: "
        f"{extra}. Document them (docs-first) before shipping, or delete the "
        f"YAML."
    )


# ---------------------------------------------------------------------------
# Adapter-ref naming convention (R3 hardening)
# ---------------------------------------------------------------------------
#
# ``adapter_ref`` is the DI seam id a fork's composition root binds an
# adapter to. Enforcing a common prefix stops accidental typos
# (``prb-adapters/…``, ``probeAdapters/…``) becoming silent runtime
# failures - the risk gate would call the resolver, get nothing back,
# and fail toward safety, but the operator would never learn why.

_ADAPTER_REF_PREFIX = "probe-adapters/"


def test_every_probe_adapter_ref_matches_naming_convention() -> None:
    catalog = load_probe_catalog(_PROBES_ROOT)
    for probe in catalog:
        assert probe.adapter_ref.startswith(_ADAPTER_REF_PREFIX), (
            f"{probe.id}: adapter_ref {probe.adapter_ref!r} must start "
            f"with {_ADAPTER_REF_PREFIX!r} (fork composition-root binding "
            "convention)"
        )
        # After the prefix, the remainder must be a kebab-case token so
        # a fork's binding table can key on it deterministically.
        remainder = probe.adapter_ref[len(_ADAPTER_REF_PREFIX):]
        assert remainder and remainder.replace("-", "").isalnum(), (
            f"{probe.id}: adapter_ref suffix {remainder!r} must be a "
            "kebab-case token"
        )


def test_every_probe_id_is_snake_case() -> None:
    import re

    catalog = load_probe_catalog(_PROBES_ROOT)
    pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    for probe in catalog:
        assert pattern.match(probe.id), (
            f"probe id {probe.id!r} must match {pattern.pattern!r} "
            "(shared audit-id shape)"
        )
