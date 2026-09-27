"""Factory-built chaos injectors declare the concrete resources they mutate."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
import yaml
from fdai.core.chaos.injector import DetectionOnlyInjector, MutationScopedInjector
from fdai.core.chaos.scenario_catalog import CatalogEntry, load_all
from fdai.delivery.chaos.factories import default_factory
from fdai.delivery.chaos.factory_bodies import _CHAOS_MESH_KINDS
from fdai.delivery.chaos.mutation_scope import (
    ScopedInjector,
    approved_catalog_targets,
    azure_resource_ref,
    kubernetes_pods_ref,
    mutation_targets_approved,
)

_SUB = "00000000-0000-0000-0000-000000000000"
_CONTEXT: dict[str, Any] = {
    "sub_id": _SUB,
    "resource_group": "rg-test",
    "kubectl_context": "ctx-test",
    "workload_namespace": "workloads",
    "workload_label": "backend",
    "chaos_namespace": "chaos",
    "litmus_namespace": "litmus",
    "litmus_service_account": "litmus-admin",
    "litmus_target_node": "node-a",
    "backend_deployment": "backend",
    "backend_service": "backend",
    "backend_container": "web",
    "backend_restore_replicas": 3,
    "backend_image": "nginx",
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
    "mysql_server_resource_id": f"/subscriptions/{_SUB}/providers/mysql-test",
    "aoai_load_request_fn": lambda: 200,
    "aoai_probe_request_fn": lambda: 429,
    "aoai_resource_id": f"/subscriptions/{_SUB}/providers/aoai-test",
    "gpu_sku_assessment_fn": lambda _targets: {"observed_sku": "H100"},
}
_VM_REF = azure_resource_ref(_CONTEXT, "Microsoft.Compute/virtualMachines", "vm-test")
_CONTEXT["vm_resource_id"] = _VM_REF
_PODS_REF = kubernetes_pods_ref(_CONTEXT)


def _executable() -> list[CatalogEntry]:
    return default_factory().executable_entries(load_all())


def _injector_for(predicate: Any) -> tuple[CatalogEntry, Any]:
    entry = next(item for item in _executable() if predicate(item))
    injector, _probe = default_factory().build(entry, dict(_CONTEXT))
    return entry, injector


def test_every_live_catalog_injector_declares_a_resolvable_mutation_scope() -> None:
    undeclared: list[str] = []
    for entry in _executable():
        injector, _probe = default_factory().build(entry, dict(_CONTEXT))
        if isinstance(injector, DetectionOnlyInjector):
            continue
        if not isinstance(injector, MutationScopedInjector):
            undeclared.append(entry.id)
            continue
        declared = injector.mutated_resources(target="unused")
        if not declared or any(not item.strip() for item in declared):
            undeclared.append(entry.id)

    assert not undeclared


def test_vm_targets_bind_the_vm_identity_the_injector_mutates() -> None:
    entry, injector = _injector_for(lambda item: item.spec["injector"] == "az:vm-lifecycle")

    targets = approved_catalog_targets(entry, _CONTEXT)

    assert targets == (_VM_REF,)
    assert injector.mutated_resources(target=_VM_REF) == (_VM_REF,)
    assert mutation_targets_approved(injector, (_VM_REF,))
    assert not mutation_targets_approved(injector, ("app=backend",))
    assert not mutation_targets_approved(injector, (_PODS_REF,))


@pytest.mark.parametrize(
    ("injector_ref", "approved"),
    [
        pytest.param("chaos-mesh:PodChaos", True, id="selector-fault-on-approved-pods"),
        pytest.param("kubectl:set-image", False, id="deployment-mutation-outside-pods"),
    ],
)
def test_pod_targets_approve_only_selector_bound_mutations(
    injector_ref: str,
    approved: bool,
) -> None:
    entry, injector = _injector_for(
        lambda item: item.spec["injector"] == injector_ref and item.spec["target_type"] == "pod"
    )

    targets = approved_catalog_targets(entry, _CONTEXT)

    assert targets == (_PODS_REF,)
    assert mutation_targets_approved(injector, targets) is approved


def test_unsupported_target_types_have_no_derived_targets() -> None:
    entry = next(item for item in _executable() if item.spec["target_type"] == "lb")

    assert approved_catalog_targets(entry, _CONTEXT) is None
    assert approved_catalog_targets(entry, {}) is None


class _SelectorInjector:
    fault_type = "pod_kill"

    def __init__(self) -> None:
        self.targets: list[str] = []

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        self.targets.append(target)

    async def stop(self, *, target: str) -> None:
        self.targets.append(target)


async def test_scoped_injector_keeps_selector_delegates_on_their_bound_selector() -> None:
    delegate = _SelectorInjector()
    scoped = ScopedInjector(delegate, resources=lambda: (_PODS_REF,), bound_target="app=backend")

    await scoped.inject(target=_PODS_REF, params={})
    await scoped.stop(target=_PODS_REF)

    assert delegate.targets == ["app=backend", "app=backend"]
    assert scoped.mutated_resources(target=_PODS_REF) == (_PODS_REF,)
    assert mutation_targets_approved(scoped, (_PODS_REF,))


def test_unscoped_and_unresolvable_injectors_are_never_approved() -> None:
    def unresolvable() -> tuple[str, ...]:
        raise KeyError("aoai_resource_id")

    assert not mutation_targets_approved(None, (_PODS_REF,))
    assert not mutation_targets_approved(_SelectorInjector(), (_PODS_REF,))
    assert not mutation_targets_approved(
        ScopedInjector(_SelectorInjector(), resources=unresolvable),
        (_PODS_REF,),
    )
    assert not mutation_targets_approved(
        ScopedInjector(_SelectorInjector(), resources=lambda: ()),
        (_PODS_REF,),
    )
    assert mutation_targets_approved(DetectionOnlyInjector(fault_type="gpu"), (_PODS_REF,))


def test_surplus_targets_are_refused_so_one_resource_is_never_injected_twice() -> None:
    _entry, vm_injector = _injector_for(lambda item: item.spec["injector"] == "az:vm-lifecycle")

    assert mutation_targets_approved(vm_injector, (_VM_REF,))
    assert not mutation_targets_approved(vm_injector, (_VM_REF, "other"))
    assert not mutation_targets_approved(vm_injector, (_VM_REF, _PODS_REF))
    per_target = ScopedInjector(_SelectorInjector(), resources=lambda: ("a", "b"))
    assert not mutation_targets_approved(per_target, ("a", "b"))


@pytest.mark.parametrize("kind", sorted(_CHAOS_MESH_KINDS))
def test_every_chaos_mesh_body_selects_exactly_its_declared_pods(kind: str) -> None:
    entry, injector = _injector_for(lambda item: item.spec["injector"] == f"chaos-mesh:{kind}")

    built_kind, body = _CHAOS_MESH_KINDS[kind](entry, dict(_CONTEXT))
    selector = yaml.safe_load(body)["spec"]["selector"]
    selected = (
        f"k8s:{_CONTEXT['kubectl_context']}/{selector['namespaces'][0]}"
        f"/pods/app={selector['labelSelectors']['app']}"
    )

    assert built_kind == kind
    assert selector == {
        "namespaces": [_CONTEXT["workload_namespace"]],
        "labelSelectors": {"app": _CONTEXT["workload_label"]},
    }
    assert injector.mutated_resources(target=selected) == (selected,)
    assert selected == _PODS_REF
