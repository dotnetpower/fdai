"""Canonical mutation-scope identities for catalog chaos injectors.

Governed enforcement binds the target lock, approval, recovery plan, and blast
radius to explicit resource identities. Every factory-built live injector is
wrapped in :class:`ScopedInjector`, which declares the concrete resources its
delegate mutates from the same substrate context values the builder bound.
:func:`approved_catalog_targets` derives the targets a catalog run must approve
from the entry's ``target_type`` and the substrate, and
:func:`mutation_targets_approved` requires each target to be exactly the one
resource its injection mutates.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fdai.core.chaos.injector import (
    DetectionOnlyInjector,
    FaultInjector,
    MutationScopedInjector,
)
from fdai.core.chaos.scenario_catalog import CatalogEntry

ResourceScope = Callable[[], tuple[str, ...]]

_POD_TARGET_TYPES = frozenset({"pod", "disk", "dns"})

# Most entries mutate the resource their `target_type` names, but a few
# injectors mutate something else: a rollout change and a replica change both
# act on the Deployment, and the managed-service load injectors act on the
# service account. Deriving those from the injector reference keeps the approved
# target equal to the mutated resource without collapsing the two derivations:
# this side reads catalog data plus the substrate context, while the built
# injector independently reports its own scope, and
# `mutation_targets_approved` still compares them.
_DEPLOYMENT_INJECTORS = frozenset({"kubectl:scale", "kubectl:set-image"})
_CONTEXT_IDENTITY_INJECTORS: dict[str, str] = {
    "mysql:query-load": "mysql_server_resource_id",
    "aoai:rate-limit": "aoai_resource_id",
}


def azure_resource_ref(context: Mapping[str, Any], provider: str, name: str) -> str:
    """Return the ARM identity of one resource in the substrate resource group."""

    return (
        f"/subscriptions/{context['sub_id']}/resourceGroups/{context['resource_group']}"
        f"/providers/{provider}/{name}"
    )


def kubernetes_pods_ref(context: Mapping[str, Any]) -> str:
    """Return the identity of the workload pods selected by ``app=<workload_label>``."""

    return (
        f"k8s:{context['kubectl_context']}/{context['workload_namespace']}"
        f"/pods/app={context['workload_label']}"
    )


def kubernetes_deployment_ref(context: Mapping[str, Any], deployment: str) -> str:
    return (
        f"k8s:{context['kubectl_context']}/{context['workload_namespace']}/deployments/{deployment}"
    )


def kubernetes_node_ref(context: Mapping[str, Any], node: str) -> str:
    return f"k8s:{context['kubectl_context']}/nodes/{node}"


class ScopedInjector:
    """Delegate to one injector while declaring the resources it mutates.

    ``resources`` is evaluated lazily so dispatchability checks keep their
    existing context contract; an unresolvable scope is never approved.
    ``bound_target`` replaces the harness target for delegates that read it,
    so a canonical target identity is never reinterpreted as a selector.
    """

    def __init__(
        self,
        injector: FaultInjector,
        *,
        resources: ResourceScope,
        bound_target: str | None = None,
    ) -> None:
        self._injector = injector
        self._resources = resources
        self._bound_target = bound_target

    @property
    def fault_type(self) -> str:
        return self._injector.fault_type

    def mutated_resources(self, *, target: str) -> tuple[str, ...]:
        return self._resources()

    async def inject(self, *, target: str, params: Mapping[str, str]) -> None:
        await self._injector.inject(target=self._bound_target or target, params=params)

    async def stop(self, *, target: str) -> None:
        await self._injector.stop(target=self._bound_target or target)


def approved_catalog_targets(
    entry: CatalogEntry,
    context: Mapping[str, Any],
) -> tuple[str, ...] | None:
    """Return the targets one catalog run must approve, or ``None`` when unsupported.

    The injector reference decides first, because an entry's ``target_type``
    names what the fault is about rather than what the injection writes to: a
    rollout or replica change acts on the Deployment, and the managed-service
    load injectors act on the database or model account. Everything else falls
    back to the ``target_type`` default. A target whose substrate value is absent
    yields ``None``, so the run is refused before any injection.
    """

    injector_ref = str(entry.spec.get("injector", ""))
    target_type = str(entry.spec.get("target_type", ""))
    try:
        if injector_ref in _DEPLOYMENT_INJECTORS:
            return (kubernetes_deployment_ref(context, str(context["backend_deployment"])),)
        identity_key = _CONTEXT_IDENTITY_INJECTORS.get(injector_ref)
        if identity_key is not None:
            return (str(context[identity_key]),)
        if target_type == "vm":
            vm_ref = azure_resource_ref(
                context,
                "Microsoft.Compute/virtualMachines",
                str(context["vm_name"]),
            )
            return (vm_ref,)
        if target_type in _POD_TARGET_TYPES:
            return (kubernetes_pods_ref(context),)
    except KeyError:
        return None
    return None


def mutation_targets_approved(
    injector: FaultInjector | None,
    targets: Sequence[str],
) -> bool:
    """Return whether each target is exactly the one resource its injection mutates.

    The harness injects once per approved target. Requiring every target to
    declare itself, and nothing else, rejects both a mutation outside the
    targets and a surplus target that would inject the same resource twice.
    """

    if injector is None or not targets:
        return False
    if isinstance(injector, DetectionOnlyInjector):
        return True
    if not isinstance(injector, MutationScopedInjector):
        return False
    try:
        return all(set(injector.mutated_resources(target=target)) == {target} for target in targets)
    except Exception:  # noqa: BLE001 - an unresolvable mutation scope is never approved
        return False


__all__ = [
    "ResourceScope",
    "ScopedInjector",
    "approved_catalog_targets",
    "azure_resource_ref",
    "kubernetes_deployment_ref",
    "kubernetes_node_ref",
    "kubernetes_pods_ref",
    "mutation_targets_approved",
]
