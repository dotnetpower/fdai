"""Demo workload: rendering, scope guard, rollout check, and rollback in one namespace.

This is the narrow apply path for the Lifecycle demo, not the workload renderer of #1946. Each
component that a Plan Entity runs becomes one Deployment and one Service named after the
component. The agent applies them with Kubernetes server-side apply under its own field manager.
Every manifest passes the scope guard before any cluster call: the configured namespace, a
Deployment or a Service, and the agent's managed-by label.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

FIELD_MANAGER = "fdai-lifecycle-agent"
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
ENTITY_LABEL = "fdai.io/entity"
COMPONENT_LABEL = "fdai.io/component"
API_VERSIONS = {"Deployment": "apps/v1", "Service": "v1"}
CONTAINER_PORT = 8080

_DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?\Z", re.ASCII)
_LABEL_VALUE = re.compile(r"[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?\Z", re.ASCII)
_REPOSITORY = re.compile(
    r"[a-z0-9]+([._-][a-z0-9]+)*(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)*\Z", re.ASCII
)
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)

type Manifest = Mapping[str, Any]
type ObjectKey = tuple[str, str]


class WorkloadError(Exception):
    """A workload step failed; carries a stable reason code."""

    def __init__(self, reason_code: str, *, retryable: bool = False) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retryable = retryable


class Cluster(Protocol):
    """One namespace of one cluster. Every failed call raises ``WorkloadError``."""

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None: ...

    def get(self, kind: str, name: str) -> Manifest | None:
        """Return the live object, or ``None`` when it doesn't exist."""
        ...

    def delete(self, kind: str, name: str) -> None:
        """Delete the object; an absent object is not an error."""
        ...


def is_dns_label(value: str) -> bool:
    """Whether ``value`` can name a namespace or an object of this workload."""

    return _DNS_LABEL.fullmatch(value) is not None


def is_repository(value: str) -> bool:
    """Whether ``value`` is an image repository path without a tag or digest."""

    return _REPOSITORY.fullmatch(value) is not None


def object_key(manifest: Manifest) -> ObjectKey:
    return manifest["kind"], manifest["metadata"]["name"]


def render(namespace: str, images: Mapping[tuple[str, str], str]) -> tuple[Manifest, ...]:
    """Render a Deployment and a Service for each ``(entity_id, component)`` image reference.

    Raises ``WorkloadError`` (``workload_render_failed``) for a name Kubernetes can't hold, an
    image reference that isn't ``repository@sha256:<hex>``, or a component in two Entities.
    """

    components = [component for _, component in images]
    if len(set(components)) != len(components):
        raise WorkloadError("workload_render_failed")
    manifests: list[Manifest] = []
    for (entity_id, component), image in sorted(images.items()):
        repository, _, digest = image.partition("@")
        if not (
            is_dns_label(component)
            and _LABEL_VALUE.fullmatch(entity_id)
            and is_repository(repository)
            and _IMAGE_DIGEST.fullmatch(digest)
        ):
            raise WorkloadError("workload_render_failed")
        labels = {
            MANAGED_BY_LABEL: FIELD_MANAGER,
            ENTITY_LABEL: entity_id,
            COMPONENT_LABEL: component,
        }
        metadata = {"name": component, "namespace": namespace, "labels": labels}
        selector = {COMPONENT_LABEL: component}
        manifests.append(_deployment(metadata, selector, labels, image))
        manifests.append(_service(metadata, selector))
    return tuple(manifests)


def _deployment(
    metadata: Mapping[str, object],
    selector: Mapping[str, str],
    labels: Mapping[str, str],
    image: str,
) -> Manifest:
    container = {
        "name": "app",
        "image": image,
        "ports": [{"name": "http", "containerPort": CONTAINER_PORT}],
        "readinessProbe": {"httpGet": {"path": "/", "port": "http"}, "periodSeconds": 2},
        "resources": {
            "requests": {"cpu": "10m", "memory": "32Mi"},
            "limits": {"memory": "64Mi"},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
        },
    }
    return {
        "apiVersion": API_VERSIONS["Deployment"],
        "kind": "Deployment",
        "metadata": metadata,
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": selector},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [container],
                },
            },
        },
    }


def _service(metadata: Mapping[str, object], selector: Mapping[str, str]) -> Manifest:
    return {
        "apiVersion": API_VERSIONS["Service"],
        "kind": "Service",
        "metadata": metadata,
        "spec": {
            "selector": selector,
            "ports": [{"name": "http", "port": 80, "targetPort": "http"}],
        },
    }


def check_scope(manifests: Iterable[Manifest], namespace: str) -> None:
    """Raise ``WorkloadError`` (``workload_outside_scope``) unless every manifest is an agent-
    managed Deployment or Service in ``namespace``."""

    for manifest in manifests:
        metadata = manifest.get("metadata")
        if not (
            isinstance(metadata, Mapping)
            and API_VERSIONS.get(manifest.get("kind", "")) == manifest.get("apiVersion")
            and metadata.get("namespace") == namespace
            and isinstance(metadata.get("name"), str)
            and isinstance(labels := metadata.get("labels"), Mapping)
            and labels.get(MANAGED_BY_LABEL) == FIELD_MANAGER
        ):
            raise WorkloadError("workload_outside_scope")


def rollout_complete(deployment: Manifest) -> bool:
    """Whether the controller observed the latest spec and every replica is updated, available,
    and ready, with no old replica left."""

    spec = deployment.get("spec") or {}
    status = deployment.get("status") or {}
    generation = (deployment.get("metadata") or {}).get("generation", 0)
    replicas = spec.get("replicas", 1)
    return status.get("observedGeneration", -1) >= generation and all(
        status.get(field, 0) == replicas
        for field in ("replicas", "updatedReplicas", "availableReplicas", "readyReplicas")
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class Workload:
    """Applies, verifies, and rolls back the rendered objects in one namespace."""

    cluster: Cluster
    namespace: str
    health_timeout_seconds: float
    poll_interval_seconds: float = 2.0
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def preflight(self, desired: Sequence[Manifest], previous: Sequence[Manifest]) -> None:
        """Check before the apply-started report, without changing the cluster.

        The change stays in scope, every desired object without a recorded healthy version is
        absent, so a rollback can restore it by deletion, and the API server accepts a
        server-side dry run of each object.
        """

        check_scope([*desired, *previous], self.namespace)
        recorded = {object_key(manifest) for manifest in previous}
        for key in map(object_key, desired):
            if key not in recorded and self.cluster.get(*key) is not None:
                raise WorkloadError("rollback_target_unknown")
        for manifest in desired:
            self.cluster.apply(manifest, dry_run=True)

    def apply(self, desired: Sequence[Manifest]) -> bool:
        """Apply ``desired`` and return whether every Deployment rolled out in time."""

        check_scope(desired, self.namespace)
        for manifest in desired:
            self.cluster.apply(manifest)
        return self._wait_until(lambda: self._rolled_out(desired))

    def roll_back(self, desired: Sequence[Manifest], previous: Sequence[Manifest]) -> bool:
        """Restore the recorded healthy objects, delete the desired objects that had none, and
        return whether that state was verified in time."""

        check_scope([*desired, *previous], self.namespace)
        recorded = {object_key(manifest) for manifest in previous}
        created = [key for key in map(object_key, desired) if key not in recorded]
        for manifest in previous:
            self.cluster.apply(manifest)
        for kind, name in created:
            self.cluster.delete(kind, name)
        return self._wait_until(
            lambda: (
                self._rolled_out(previous)
                and all(self.cluster.get(kind, name) is None for kind, name in created)
            )
        )

    def _rolled_out(self, manifests: Sequence[Manifest]) -> bool:
        """Whether every object exists and, for a Deployment, its rollout is complete."""

        for kind, name in map(object_key, manifests):
            live = self.cluster.get(kind, name)
            if live is None:
                return False
            if kind == "Deployment" and not rollout_complete(live):
                return False
        return True

    def _wait_until(self, condition: Callable[[], bool]) -> bool:
        """Poll ``condition`` until the health timeout.

        A retryable read failure counts as not yet true. A non-retryable one, such as a
        rejected request, ends the check at once instead of waiting out the full timeout.
        """

        deadline = self.monotonic() + self.health_timeout_seconds
        while True:
            try:
                if condition():
                    return True
            except WorkloadError as error:
                if not error.retryable:
                    raise
            if self.monotonic() >= deadline:
                return False
            self.sleep(self.poll_interval_seconds)
