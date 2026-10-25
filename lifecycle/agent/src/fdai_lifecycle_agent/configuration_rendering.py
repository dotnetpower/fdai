"""Dispatch signed configuration to independently approved workload renderers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from fdai_deployment_cli.lifecycle_plan import LifecyclePlan
from fdai_deployment_cli.lifecycle_release import (
    APPLICATION_COMPONENT_RELEASE_SCHEMA,
    APPLICATION_RELEASE_SCHEMAS,
)

from fdai_lifecycle_agent.inputs import VerifiedConfiguration, VerifiedRelease
from fdai_lifecycle_agent.journal import WorkloadStore
from fdai_lifecycle_agent.operator_workload import render_operator, validate_profile
from fdai_lifecycle_agent.runtime_bundle import RuntimeBundle
from fdai_lifecycle_agent.workload import (
    ENTITY_LABEL,
    Manifest,
    Workload,
    WorkloadError,
    object_key,
    render,
)


def validate_entity_configuration(
    configuration: VerifiedConfiguration,
    components: Mapping[str, frozenset[str]],
    *,
    current_schema: int,
    release: VerifiedRelease,
    plan: LifecyclePlan,
    runtime_bundle: RuntimeBundle | None = None,
) -> None:
    """Validate public workload intent with private reference inputs, independently per Entity."""
    _validate_release_profile(release, configuration)
    if release.schema_version == APPLICATION_COMPONENT_RELEASE_SCHEMA:
        if runtime_bundle is None:
            raise WorkloadError("runtime_bundle_unavailable")
        if release.schema_target != current_schema:
            raise WorkloadError("schema_transition_unsupported")
        for entity in plan.entity_ids:
            values = (
                configuration.entity_values[entity]
                if configuration.entity_values
                else configuration.values
            )
            if values.get("runtime_bundle_digest") != runtime_bundle.digest:
                raise WorkloadError("runtime_bundle_digest_mismatch")
            render_values = (
                configuration.render_values.get(entity, values)
                if configuration.render_values
                else values
            )
            referenced = runtime_bundle.referenced_configuration_keys(entity)
            if set(render_values) - {"runtime_bundle_digest", "region"} - referenced:
                raise WorkloadError("runtime_bundle_configuration_unsupported")
            if referenced - set(render_values):
                raise WorkloadError("runtime_bundle_configuration_key_missing")
            if "region" in values and not isinstance(values["region"], str):
                raise WorkloadError("workload_region_invalid")
            if runtime_bundle.components(entity) != components[entity]:
                raise WorkloadError("runtime_bundle_component_mismatch")
        return
    if runtime_bundle is not None:
        raise WorkloadError("runtime_bundle_release_unsupported")
    if not configuration.entity_values and "workload_profile" in configuration.values:
        validate_profile(
            configuration.values,
            {entity: components[entity] for entity in plan.entity_ids},
            current_schema=current_schema,
            target_schema=release.schema_target,
            schema_minimum=release.schema_minimum,
            schema_maximum=release.schema_maximum,
        )
    for entity, values in configuration.render_values.items():
        public = configuration.entity_values[entity]
        if "region" in public and not isinstance(public["region"], str):
            raise WorkloadError("workload_region_invalid")
        if any(key in public for key in ("namespace", "component_images", "entity_components")):
            raise WorkloadError("workload_outside_scope")
        if "workload_profile" in public:
            validate_profile(
                values,
                {entity: components[entity]},
                current_schema=current_schema,
                target_schema=release.schema_target,
                schema_minimum=release.schema_minimum,
                schema_maximum=release.schema_maximum,
            )
        else:
            replicas = public.get("replicas", 1)
            if type(replicas) is not int or not 1 <= replicas <= 3:
                raise WorkloadError("workload_replicas_invalid")


def render_entity_configuration(
    namespace: str,
    images: Mapping[tuple[str, str], str],
    *,
    configuration: VerifiedConfiguration,
    core_image: str | None,
    plan: LifecyclePlan,
    release: VerifiedRelease,
) -> tuple[Manifest, ...]:
    """Only selected Entities reach renderers. References never cross to another Entity."""
    desired: list[Manifest] = []
    for entity in sorted(plan.entity_ids):
        values = configuration.render_values[entity]
        own_images = {key: value for key, value in images.items() if key[0] == entity}
        if "workload_profile" in configuration.entity_values[entity]:
            if core_image is None:
                raise WorkloadError("workload_render_failed")
            rendered = render_operator(
                namespace,
                own_images,
                core_image=core_image,
                values=values,
                plan_digest=hashlib.sha256(plan.signed_payload).hexdigest(),
            )
        else:
            rendered = render(namespace, own_images, specifications=release.workloads or None)
            for manifest in rendered:
                if manifest["kind"] == "Deployment":
                    manifest["spec"]["replicas"] = values.get(
                        "replicas", manifest["spec"]["replicas"]
                    )
        desired.extend(rendered)
    if len({object_key(item) for item in desired}) != len(desired):
        raise WorkloadError("workload_render_failed")
    return tuple(desired)


def prepare_workload(
    plan: LifecyclePlan,
    release: VerifiedRelease,
    configuration: VerifiedConfiguration,
    *,
    entity_components: Mapping[str, frozenset[str]],
    component_repositories: Mapping[str, str],
    workload: Workload,
    store: WorkloadStore,
    runtime_bundle: RuntimeBundle | None = None,
) -> tuple[tuple[Manifest, ...], tuple[Manifest, ...]]:
    """Render and server-dry-run approved workloads before writing the intent journal."""
    _validate_release_profile(release, configuration)
    try:
        images = {
            (entity, component): f"{component_repositories[component]}"
            f"@{release.component_images[component]}"
            for entity in plan.entity_ids
            for component in entity_components[entity]
        }
    except KeyError:
        raise WorkloadError("workload_render_failed") from None
    values = configuration.values
    repository = component_repositories.get("core-control-plane")
    digest = release.component_images.get("core-control-plane")
    core_image = f"{repository}@{digest}" if repository and digest else None
    if release.schema_version == APPLICATION_COMPONENT_RELEASE_SCHEMA:
        if runtime_bundle is None:
            raise WorkloadError("runtime_bundle_unavailable")
        store.require_private()
        configuration_values = configuration.render_values or {
            entity: configuration.values for entity in plan.entity_ids
        }
        desired = runtime_bundle.render(
            workload.namespace,
            plan.entity_ids,
            images,
            configuration_values=configuration_values,
        )
    elif configuration.entity_values:
        store.require_private()
        desired = render_entity_configuration(
            workload.namespace,
            images,
            configuration=configuration,
            core_image=core_image,
            plan=plan,
            release=release,
        )
    elif "workload_profile" in values:
        if core_image is None:
            raise WorkloadError("workload_render_failed")
        desired = render_operator(
            workload.namespace,
            images,
            core_image=core_image,
            values=values,
            plan_digest=hashlib.sha256(plan.signed_payload).hexdigest(),
        )
    else:
        desired = render(workload.namespace, images, specifications=release.workloads or None)
    healthy = {object_key(manifest): manifest for manifest in store.load().healthy}
    if runtime_bundle is not None:
        desired_by_key = {object_key(manifest): manifest for manifest in desired}
        for key, item in healthy.items():
            entity = item["metadata"]["labels"].get(ENTITY_LABEL)
            if key in desired_by_key:
                if entity != desired_by_key[key]["metadata"]["labels"].get(ENTITY_LABEL):
                    raise WorkloadError("runtime_bundle_entity_reassignment_unsupported")
            elif entity in plan.entity_ids:
                raise WorkloadError("runtime_bundle_topology_removal_unsupported")
    previous = tuple(healthy[key] for key in map(object_key, desired) if key in healthy)
    workload.preflight(desired, previous)
    return desired, previous


def _validate_release_profile(
    release: VerifiedRelease, configuration: VerifiedConfiguration
) -> None:
    values = (configuration.values, *configuration.entity_values.values())
    if release.schema_version in APPLICATION_RELEASE_SCHEMAS and any(
        "workload_profile" in value for value in values
    ):
        raise WorkloadError("application_workload_profile_unsupported")
