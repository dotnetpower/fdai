"""Namespace-scoped apply and recovery for approved workload profiles.

The legacy renderer and read-only Operator schema Job remain available. Private runtime bundles
add bounded workloads and schedules. Every manifest passes the scope guard before cluster writes.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from fdai_deployment_cli.lifecycle_release import HttpWorkload

if TYPE_CHECKING:
    from fdai_lifecycle_agent.adoption import AdoptionExpectation

FIELD_MANAGER = "fdai-lifecycle-agent"
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
ENTITY_LABEL = "fdai.io/entity"
COMPONENT_LABEL = "fdai.io/component"
SCHEMA_EXPAND_ANNOTATION = "fdai.io/schema-expand"
SCHEMA_TARGET_ANNOTATION = "fdai.io/schema-target"
API_VERSIONS = {
    "Deployment": "apps/v1",
    "Service": "v1",
    "Job": "batch/v1",
    "CronJob": "batch/v1",
    "HorizontalPodAutoscaler": "autoscaling/v2",
}
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


class CreationRejectedError(WorkloadError):
    """The provider confirmed rejection before creating the requested object."""


class MutationNotSubmittedError(WorkloadError):
    """A local submission guard denied a mutation before its request was sent."""


class Cluster(Protocol):
    """One namespace of one cluster. Every failed call raises ``WorkloadError``."""

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None: ...

    def get(self, kind: str, name: str) -> Manifest | None:
        """Return the live object, or ``None`` when it doesn't exist."""
        ...

    def delete(self, kind: str, name: str) -> None:
        """Delete the object; an absent object is not an error."""
        ...


@runtime_checkable
class OwnershipTransitionCluster(Cluster, Protocol):
    def transition_owned(self, kind: str, name: str, uid: str) -> bool: ...

    def transition_live(self, kind: str, name: str, uid: str) -> Manifest | None: ...


def is_dns_label(value: str) -> bool:
    """Whether ``value`` can name a namespace or an object of this workload."""

    return _DNS_LABEL.fullmatch(value) is not None


def is_repository(value: str) -> bool:
    """Whether ``value`` is an image repository path without a tag or digest."""

    return _REPOSITORY.fullmatch(value) is not None


def object_key(manifest: Manifest) -> ObjectKey:
    return manifest["kind"], manifest["metadata"]["name"]


def is_schema_expand_job(manifest: Manifest) -> bool:
    return (
        manifest.get("kind") == "Job"
        and manifest.get("metadata", {}).get("annotations", {}).get(SCHEMA_EXPAND_ANNOTATION)
        == "true"
    )


def render(
    namespace: str,
    images: Mapping[tuple[str, str], str],
    *,
    specifications: Mapping[str, HttpWorkload] | None = None,
) -> tuple[Manifest, ...]:
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
        deployment = _deployment(metadata, selector, labels, image)
        if specifications is not None:
            if component not in specifications:
                raise WorkloadError("workload_render_failed")
            specification = specifications[component]
            deployment["spec"]["replicas"] = specification.replicas
            container = deployment["spec"]["template"]["spec"]["containers"][0]
            container["ports"][0]["containerPort"] = specification.port
            container["readinessProbe"]["httpGet"]["path"] = specification.health_path
        manifests.append(deployment)
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


def check_scope(
    manifests: Iterable[Manifest],
    namespace: str,
    *,
    unmanaged_adoptions: frozenset[ObjectKey] = frozenset(),
) -> None:
    """Require agent-managed Deployments, internal Services, Jobs or CronJobs in ``namespace``."""

    for manifest in manifests:
        metadata = manifest.get("metadata")
        kind = manifest.get("kind", "")
        name = metadata.get("name") if isinstance(metadata, Mapping) else None
        if not (
            isinstance(metadata, Mapping)
            and API_VERSIONS.get(kind) == manifest.get("apiVersion")
            and metadata.get("namespace") == namespace
            and isinstance(name, str)
            and isinstance(labels := metadata.get("labels"), Mapping)
            and (
                labels.get(MANAGED_BY_LABEL) == FIELD_MANAGER or (kind, name) in unmanaged_adoptions
            )
            and (
                kind != "Service"
                or manifest.get("spec", {}).get("type", "ClusterIP") == "ClusterIP"
            )
        ):
            raise WorkloadError("workload_outside_scope")


def rollout_complete(deployment: Manifest) -> bool:
    """Whether the controller observed the latest spec and every replica is updated, available,
    and ready, with no old replica left."""

    spec = deployment.get("spec") or {}
    status = deployment.get("status") or {}
    generation = (deployment.get("metadata") or {}).get("generation", 0)
    # An autoscaled Deployment omits replicas; the controller-reported count is then the target.
    replicas = spec["replicas"] if "replicas" in spec else status.get("replicas", 0)
    if replicas < 1 and "replicas" not in spec:
        return False
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

    def preflight(
        self,
        desired: Sequence[Manifest],
        previous: Sequence[Manifest],
        *,
        adoptions: Sequence[AdoptionExpectation] = (),
    ) -> None:
        """Check before the apply-started report, without changing the cluster.

        The change stays in scope, every desired object without a recorded healthy version is
        absent, so a rollback can restore it by deletion, and the API server accepts a
        server-side dry run of each object.
        """

        check_scope(desired, self.namespace)
        check_scope(
            previous,
            self.namespace,
            unmanaged_adoptions=frozenset(item.key for item in adoptions),
        )
        recorded = {object_key(manifest) for manifest in previous}
        for key in map(object_key, desired):
            if key not in recorded and self.cluster.get(*key) is not None:
                raise WorkloadError("rollback_target_unknown")
        for manifest in desired:
            self.cluster.apply(manifest, dry_run=True)

    def apply(
        self,
        desired: Sequence[Manifest],
        *,
        can_continue: Callable[[], bool] | None = None,
    ) -> bool:
        """Complete schema-check Jobs before switching workloads, then verify and clean up.

        Jobs only verify the existing schema. Their failure or timeout cannot switch a
        Deployment. An interrupted apply restores the journal without re-running a Job.
        """

        check_scope(desired, self.namespace)
        jobs = tuple(item for item in desired if item["kind"] == "Job")
        scheduled = tuple(item for item in desired if item["kind"] == "CronJob")
        for item in scheduled:
            _check_deadline(can_continue)
            self.cluster.apply(_suspended_schedule(item))
        for job in jobs:
            _check_deadline(can_continue)
            self.cluster.apply(job)
        if jobs and not self._wait_until(
            lambda: self._jobs_complete(jobs), can_continue=can_continue
        ):
            raise WorkloadError("schema_check_failed")
        # An autoscaler is applied after its target Deployment exists.
        for manifest in sorted(
            (item for item in desired if item["kind"] not in {"Job", "CronJob"}),
            key=lambda item: item["kind"] == "HorizontalPodAutoscaler",
        ):
            _check_deadline(can_continue)
            self.cluster.apply(manifest)
        immediate = tuple(item for item in desired if item["kind"] != "CronJob")
        if not self._wait_until(lambda: self._rolled_out(immediate), can_continue=can_continue):
            return False
        for item in scheduled:
            _check_deadline(can_continue)
            self.cluster.apply(item)
        if scheduled and not self._wait_until(
            lambda: self._rolled_out(scheduled), can_continue=can_continue
        ):
            raise WorkloadError("scheduled_activation_unverified")
        cleanup_jobs = tuple(job for job in jobs if not is_schema_expand_job(job))
        for job in cleanup_jobs:
            self.cluster.delete(*object_key(job))
        if cleanup_jobs and not self._wait_until(
            lambda: all(self.cluster.get(*object_key(job)) is None for job in cleanup_jobs)
        ):
            raise WorkloadError("schema_check_cleanup_failed")
        return True

    def roll_back(
        self,
        desired: Sequence[Manifest],
        previous: Sequence[Manifest],
        *,
        adoptions: Sequence[AdoptionExpectation] = (),
    ) -> bool:
        """Restore the recorded healthy objects, delete the desired objects that had none, and
        return whether that state was verified in time."""

        check_scope(desired, self.namespace)
        check_scope(
            previous,
            self.namespace,
            unmanaged_adoptions=frozenset(item.key for item in adoptions),
        )
        # A suspended/missing template cannot prove that an earlier activation never ran.
        unproved_scheduled_effect = any(
            item["kind"] == "CronJob" and item.get("spec", {}).get("suspend") is not True
            for item in (*desired, *previous)
        )
        for item in desired:
            if item["kind"] != "CronJob":
                continue
            live = self.cluster.get(*object_key(item))
            if live is not None:
                unproved_scheduled_effect |= live.get("spec", {}).get("suspend") is not True
                self.cluster.apply(_suspended_schedule(item))
        recorded = {object_key(manifest) for manifest in previous}
        created = [key for key in map(object_key, desired) if key not in recorded]
        migration_jobs = {
            object_key(manifest) for manifest in desired if is_schema_expand_job(manifest)
        }
        for kind, name in created:
            if kind == "Job" and (kind, name) not in migration_jobs:
                self.cluster.delete(kind, name)
        # A running Job must be absent before restoring or removing any workload.
        if not self._wait_until(
            lambda: all(
                self.cluster.get(kind, name) is None
                for kind, name in created
                if kind == "Job" and (kind, name) not in migration_jobs
            )
        ):
            return False
        transition = self.cluster if isinstance(self.cluster, OwnershipTransitionCluster) else None
        adoption_by_key = {item.key: item for item in adoptions}
        unadopted_previous: list[Manifest] = []
        previous_to_apply: list[Manifest] = []
        for manifest in previous:
            key = object_key(manifest)
            expectation = adoption_by_key.get(key)
            if (
                expectation is not None
                and transition is not None
                and not transition.transition_owned(*key, expectation.uid)
            ):
                unadopted_previous.append(manifest)
            else:
                previous_to_apply.append(manifest)
        for manifest in previous_to_apply:
            self.cluster.apply(
                _suspended_schedule(manifest)
                if manifest["kind"] == "CronJob" and unproved_scheduled_effect
                else manifest
            )
        for kind, name in created:
            if kind != "Job":
                self.cluster.delete(kind, name)
        restored = self._wait_until(
            lambda: (
                self._rolled_out(
                    tuple(
                        _suspended_schedule(item)
                        if item["kind"] == "CronJob" and unproved_scheduled_effect
                        else item
                        for item in previous_to_apply
                    )
                )
                and all(
                    transition is not None
                    and (expectation := adoption_by_key.get(object_key(item))) is not None
                    and (live := transition.transition_live(*object_key(item), expectation.uid))
                    is not None
                    and _contains(live.get("spec"), item.get("spec"))
                    for item in unadopted_previous
                )
                and all(
                    self.cluster.get(kind, name) is None
                    for kind, name in created
                    if (kind, name) not in migration_jobs
                )
            )
        )
        return restored and not unproved_scheduled_effect

    def completed_schema_revision(self, desired: Sequence[Manifest]) -> int | None:
        """Return the retained completed migration receipt's schema target, if any."""

        targets: list[int] = []
        for manifest in desired:
            if not is_schema_expand_job(manifest):
                continue
            live = self.cluster.get(*object_key(manifest))
            conditions = [] if live is None else live.get("status", {}).get("conditions", [])
            if not any(
                item.get("type") == "Complete" and item.get("status") == "True"
                for item in conditions
            ):
                continue
            target = (
                manifest.get("metadata", {}).get("annotations", {}).get(SCHEMA_TARGET_ANNOTATION)
            )
            if not isinstance(target, str) or not target.isdecimal():
                raise WorkloadError("schema_expand_receipt_invalid")
            targets.append(int(target))
        return max(targets) if targets else None

    def _rolled_out(self, manifests: Sequence[Manifest]) -> bool:
        """Whether every object exists and, for a Deployment, its rollout is complete."""

        for manifest in manifests:
            kind, name = object_key(manifest)
            live = self.cluster.get(kind, name)
            if live is None or live.get("metadata", {}).get("deletionTimestamp") is not None:
                return False
            if not _contains(live.get("spec"), manifest.get("spec")):
                return False
            if kind == "Deployment":
                if not rollout_complete(live):
                    return False
        return True

    def drifted_entities(
        self, expected: Sequence[Manifest]
    ) -> tuple[dict[str, frozenset[str]], frozenset[str]]:
        """Compare live Deployments against recorded healthy manifests.

        Returns ``(drifted_by_entity, expected_image_digests)`` where ``drifted_by_entity``
        maps each drifted Entity id to the valid ``sha256:<hex>`` image digests currently
        observed on its live Deployments.
        """

        drifted: set[str] = set()
        live_digests: dict[str, set[str]] = {}
        expected_digests: set[str] = set()
        for manifest in expected:
            if manifest.get("kind") not in {"Deployment", "CronJob"}:
                continue
            metadata = manifest.get("metadata") or {}
            labels = metadata.get("labels") or {}
            entity_id = labels.get(ENTITY_LABEL)
            name = metadata.get("name")
            if not isinstance(entity_id, str) or not isinstance(name, str):
                continue
            expected_digests.update(deployment_image_digests(manifest))
            live = self.cluster.get(manifest["kind"], name)
            if (
                live is None
                or (live.get("metadata") or {}).get("deletionTimestamp") is not None
                or not _contains(live.get("spec"), manifest.get("spec"))
            ):
                drifted.add(entity_id)
            if live is not None:
                live_digests.setdefault(entity_id, set()).update(deployment_image_digests(live))
        return (
            {
                entity_id: frozenset(live_digests.get(entity_id, set()))
                for entity_id in sorted(drifted)
            },
            frozenset(expected_digests),
        )

    def _jobs_complete(self, jobs: Sequence[Manifest]) -> bool:
        complete = True
        for job in jobs:
            live = self.cluster.get(*object_key(job))
            if live is not None and not _contains(live.get("spec"), job.get("spec")):
                raise WorkloadError("schema_check_failed")
            conditions = (live or {}).get("status", {}).get("conditions", [])
            if any(
                item.get("type") == "Failed" and item.get("status") == "True" for item in conditions
            ):
                raise WorkloadError("schema_check_failed")
            if not any(
                item.get("type") == "Complete" and item.get("status") == "True"
                for item in conditions
            ):
                complete = False
        return complete

    def _wait_until(
        self,
        condition: Callable[[], bool],
        *,
        can_continue: Callable[[], bool] | None = None,
    ) -> bool:
        """Poll ``condition`` until the health timeout.

        A retryable read failure counts as not yet true. A non-retryable one, such as a
        rejected request, ends the check at once instead of waiting out the full timeout.
        """

        deadline = self.monotonic() + self.health_timeout_seconds
        while True:
            _check_deadline(can_continue)
            try:
                if condition():
                    return True
            except WorkloadError as error:
                if not error.retryable:
                    raise
            if self.monotonic() >= deadline:
                return False
            self.sleep(self.poll_interval_seconds)


def _check_deadline(can_continue: Callable[[], bool] | None) -> None:
    if can_continue is not None and not can_continue():
        raise WorkloadError("plan_expired")


def _suspended_schedule(manifest: Manifest) -> Manifest:
    return dict(manifest) | {"spec": dict(manifest["spec"]) | {"suspend": True}}


def deployment_image_digests(manifest: Manifest) -> tuple[str, ...]:
    spec = manifest.get("spec") or {}
    if manifest.get("kind") == "CronJob":
        spec = spec.get("jobTemplate", {}).get("spec", {})
    pod = (spec.get("template") or {}).get("spec") or {}
    containers = [*pod.get("containers", []), *pod.get("initContainers", [])]
    if not isinstance(containers, Sequence):
        return ()
    digests: list[str] = []
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        image = container.get("image")
        if isinstance(image, str):
            _, _, digest = image.partition("@")
            if _IMAGE_DIGEST.fullmatch(digest):
                digests.append(digest)
    return tuple(digests)


def _contains(actual: object, desired: object) -> bool:
    """Read back rendered fields while tolerating Kubernetes-added object defaults."""

    if isinstance(desired, Mapping):
        return isinstance(actual, Mapping) and all(
            key in actual and _contains(actual[key], value) for key, value in desired.items()
        )
    if isinstance(desired, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(desired)
            and all(
                _contains(live, expected) for live, expected in zip(actual, desired, strict=True)
            )
        )
    return actual == desired
