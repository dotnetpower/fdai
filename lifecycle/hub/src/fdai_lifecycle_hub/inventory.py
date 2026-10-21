"""Read-only projections, not artifact availability or execution authority."""

from __future__ import annotations

from dataclasses import asdict

from fdai_deployment_cli.lifecycle_release import LIFECYCLE_IMAGE_SECTIONS

from fdai_lifecycle_hub.catalog import ReleaseCatalog


def release_inventory(catalog: ReleaseCatalog) -> dict[str, object]:
    releases = []
    for release_id, release in sorted(catalog.releases.items()):
        manifest = release.to_mapping()
        images = []
        for section in LIFECYCLE_IMAGE_SECTIONS:
            components = manifest.get(section, {})
            if not isinstance(components, dict):
                raise ValueError("Release image section must be an object.")
            for component, artifact in sorted(components.items()):
                if not isinstance(artifact, dict) or not isinstance(
                    artifact.get("image_digest"), str
                ):
                    raise ValueError("Release image metadata must include a digest.")
                images.append(
                    {
                        "section": section,
                        "component": component,
                        "image_digest": artifact["image_digest"],
                    }
                )
        releases.append(
            {
                "release_id": release_id,
                "digest": release.digest,
                "source_commit": release.source_commit,
                "platform_tag": release.platform_tag,
                "channels": sorted(
                    name for name, members in catalog.channels.items() if release_id in members
                ),
                "schema_target": release.schema_target,
                "schema_range": asdict(release.schema_range) if release.schema_range else None,
                "images": images,
                "recall_notices": [
                    asdict(notice)
                    for notice in catalog.recalls
                    if notice.scope == "release" and notice.target == release_id
                ],
            }
        )
    return {"releases": releases}
