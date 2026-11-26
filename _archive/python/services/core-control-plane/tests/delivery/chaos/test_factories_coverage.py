"""Coverage tests for the delivery-layer chaos-scenario factory.

Locks the invariant that **every non-`needs-injector` catalog entry
built by the default factory is dispatchable end-to-end** (both
injector and probe instantiate without error against a synthetic
context). If someone adds a scenario to the catalog whose
`injector` string the delivery layer does not know how to build,
this test fails immediately.

Also asserts the two coverage numbers we cite in
`docs/internals/sre-scenario-library-scaling.md`:

- `needs-injector` correctly maps to `is_executable == False`, so
  the factory never accidentally tries to inject them.
- The default factory registers builders for every prefix / kind
  the seed generator + Chaos Mesh ingester emit.
"""

from __future__ import annotations

from typing import Any

from fdai.core.chaos.factory import NON_EXECUTABLE_MARKERS
from fdai.core.chaos.scenario_catalog import load_all
from fdai.delivery.chaos.factories import default_factory


def _synthetic_context() -> dict[str, Any]:
    """A test context with all fields any builder might read.

    Uses the all-zero GUID placeholder for the subscription so the
    generic-scope check-guids gate does not flag this file.
    """
    return {
        "sub_id": "00000000-0000-0000-0000-000000000000",
        "kubectl_context": "test-ctx",
        "workload_namespace": "demo",
        "workload_label": "api-backend",
        "chaos_namespace": "chaos-mesh",
        "litmus_namespace": "litmus",
        "litmus_service_account": "litmus-admin",
        "litmus_target_node": "node-test",
        "backend_deployment": "api-backend",
        "backend_service": "api-backend",
        "backend_container": "web",
        "backend_restore_replicas": 3,
        "backend_image": "nginx",
        "resource_group": "rg-test",
        "vm_name": "vm-test",
        "vmss_name": "vmss-test",
        "redis_cache_name": "redis-test",
        "cosmos_account_name": "cosmos-test",
        "keyvault_name": "kv-test",
        "nsg_name": "nsg-test",
        "lb_name": "lb-test",
        "lb_pool_name": "pool-test",
        "lb_address_name": "addr-test",
        "servicebus_namespace": "sb-test",
        "mysql_connect_factory": lambda: None,
        "mysql_server_resource_id": (
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg-test/providers/Microsoft.DBforMySQL"
            "/flexibleServers/mysql-test"
        ),
        "aoai_load_request_fn": lambda: 200,
        "aoai_probe_request_fn": lambda: 429,
        "gpu_sku_assessment_fn": lambda _targets: {
            "observed_sku": "H100",
            "recommended_sku": "A100",
            "confidence": 0.9,
        },
        "vm_resource_id": (
            "/subscriptions/00000000-0000-0000-0000-000000000000"
            "/resourceGroups/rg-test/providers/Microsoft.Compute"
            "/virtualMachines/vm-test"
        ),
    }


def test_non_executable_marker_entries_are_not_executable() -> None:
    """Both `needs-injector` (delivery adapter TBD) and
    `cross-csp-reference` (borrowed catalog data on an Azure-only
    stack) are reported as non-executable so nothing accidentally
    injects them."""
    factory = default_factory()
    entries = load_all()
    non_exec = [e for e in entries if e.spec["injector"] in NON_EXECUTABLE_MARKERS]
    assert non_exec, "catalog MUST contain at least one non-executable-marker entry"
    for e in non_exec:
        assert not factory.is_executable(e), (
            f"{e.id}: {e.spec['injector']!r} must never appear as executable"
        )


def test_every_wired_injector_string_has_a_builder() -> None:
    """No `chaos-mesh:*` / `kubectl:*` / `az:*` entry falls through to
    `not executable` because a builder is missing."""
    factory = default_factory()
    entries = load_all()
    missing: list[str] = []
    for e in entries:
        inj = e.spec["injector"]
        if inj in NON_EXECUTABLE_MARKERS:
            continue
        # `is_executable` == True means both an injector builder AND a
        # probe builder are registered.
        if not factory.is_executable(e):
            missing.append(f"{e.id} (injector={inj}, signal={e.expected_signal})")
    assert not missing, (
        "Catalog entries with a shipped injector string but no matching "
        "builder in fdai.delivery.chaos.factories:\n  - " + "\n  - ".join(missing)
    )


def test_every_executable_entry_builds_end_to_end() -> None:
    """Actually invoke each builder pair and confirm construction works.

    This is the stronger claim: not only does dispatch match a builder,
    the builder itself does not raise on any executable catalog entry
    for any (kind, action, signal) combination.
    """
    factory = default_factory()
    ctx = _synthetic_context()
    failures: list[str] = []
    for e in factory.executable_entries(load_all()):
        try:
            factory.build(e, ctx)
        except Exception as exc:  # noqa: BLE001 - report per-entry, then assert
            failures.append(f"{e.id}: {type(exc).__name__}:{exc}")
    assert not failures, "builder(s) raised for executable catalog entries:\n  - " + "\n  - ".join(
        failures
    )


def test_executable_count_matches_catalog_split() -> None:
    """Sanity: executable + non-executable == total, and non-executable
    is exactly the union of the non-executable-marker sets
    (needs-injector + cross-csp-reference)."""
    factory = default_factory()
    entries = load_all()
    executable = factory.executable_entries(entries)
    non_exec_marked = [e for e in entries if e.spec["injector"] in NON_EXECUTABLE_MARKERS]
    assert len(executable) + len(non_exec_marked) == len(entries), (
        "the only reason an entry is non-executable in the default factory "
        "is a NON_EXECUTABLE_MARKERS injector - a probe gap would silently "
        "drop entries into non-executable and break this invariant."
    )
    assert len(executable) == 93
