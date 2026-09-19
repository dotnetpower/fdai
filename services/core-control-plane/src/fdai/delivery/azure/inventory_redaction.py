"""Remove runtime environment bindings after relationship extraction."""

from __future__ import annotations

import copy
from collections.abc import Mapping

from fdai.shared.providers.inventory import ResourceRecord


def redact_runtime_environment(resource: ResourceRecord) -> ResourceRecord:
    """Return a record whose runtime environment retains no names or binding values."""

    props = copy.deepcopy(dict(resource.props))
    properties = props.get("properties")
    if not isinstance(properties, dict):
        return resource
    template = properties.get("template")
    if not isinstance(template, dict):
        return resource
    changed = False
    for container_family in ("containers", "initContainers"):
        containers = template.get(container_family)
        if not isinstance(containers, list):
            continue
        for container in containers:
            if not isinstance(container, dict):
                continue
            environment = container.get("env")
            if not isinstance(environment, list):
                continue
            container["env"] = [
                {"bindingRedacted": True} for item in environment if isinstance(item, Mapping)
            ]
            changed = True
    if not changed:
        return resource
    return ResourceRecord(
        resource_id=resource.resource_id,
        type=resource.type,
        props=props,
        provider_ref=resource.provider_ref,
        last_seen=resource.last_seen,
    )


__all__ = ["redact_runtime_environment"]
