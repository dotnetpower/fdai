"""Cross-check configs, adoptions, ownership, and forward revision metadata."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from service_migrations.adoption import AdoptionManifest, load_adoption_manifest
from service_migrations.inventory import LegacyInventory, load_revision_metadata
from service_migrations.ownership import SERVICE_IDS, OwnershipManifest


def validate_service_branches(
    root: Path,
    inventory: LegacyInventory,
    ownership: OwnershipManifest,
) -> dict[str, AdoptionManifest]:
    """Validate five independent heads and ownership-bound forward metadata."""
    adoptions: dict[str, AdoptionManifest] = {}
    seen_revisions: set[str] = set()
    declared_table_owners: dict[str, str] = {}
    created_table_owners: dict[str, str] = {}
    branch_revisions: dict[str, set[str]] = {}
    for service_id in SERVICE_IDS:
        config_path = root / "configs" / f"{service_id}.ini"
        config = Config(str(config_path))
        if config.get_main_option("service_id") != service_id:
            raise ValueError(f"{config_path}: service_id mismatch")
        adoption = load_adoption_manifest(
            root / "branches" / service_id / "adoption.json",
            service_id=service_id,
            inventory=inventory,
        )
        if config.get_main_option("version_table") != adoption.service_version_table:
            raise ValueError(f"{config_path}: version_table does not match adoption")
        script = ScriptDirectory.from_config(config)
        heads = tuple(script.get_heads())
        if len(heads) != 1:
            raise ValueError(f"{service_id}: expected one head, found {heads}")
        revisions = {revision.revision for revision in script.walk_revisions()}
        branch_revisions[service_id] = revisions
        if adoption.baseline_revision not in revisions:
            raise ValueError(f"{service_id}: baseline revision is absent")

        version_location = root / "branches" / service_id / "versions"
        for path in sorted(version_location.glob("*.py")):
            metadata = load_revision_metadata(path)
            if metadata.owner != service_id:
                raise ValueError(f"{path}: migration owner must be {service_id}")
            if metadata.revision in seen_revisions:
                raise ValueError(f"duplicate revision across service branches: {metadata.revision}")
            seen_revisions.add(metadata.revision)
            for table in metadata.owned_tables:
                expected_owner = ownership.table_migrators.get(table)
                if expected_owner is None:
                    raise ValueError(f"{path}: unknown owned table {table}")
                if expected_owner != service_id:
                    raise ValueError(f"{path}: {table} belongs to migration owner {expected_owner}")
                prior_owner = declared_table_owners.setdefault(table, service_id)
                if prior_owner != service_id:
                    raise ValueError(
                        f"forward migration ownership overlaps for {table}: "
                        f"{prior_owner} and {service_id}"
                    )
            for table in metadata.created_tables:
                prior_creator = created_table_owners.setdefault(table, service_id)
                if prior_creator != service_id:
                    raise ValueError(
                        f"forward table creation overlaps for {table}: "
                        f"{prior_creator} and {service_id}"
                    )
        adoptions[service_id] = adoption
    for dependency in ownership.migration_dependencies:
        if dependency.consumer_revision not in branch_revisions[dependency.consumer_service]:
            raise ValueError(
                f"migration dependency consumer revision is absent: "
                f"{dependency.consumer_service}:{dependency.consumer_revision}"
            )
        if dependency.provider_revision not in branch_revisions[dependency.provider_service]:
            raise ValueError(
                f"migration dependency provider revision is absent: "
                f"{dependency.provider_service}:{dependency.provider_revision}"
            )
    if len({adoption.service_version_table for adoption in adoptions.values()}) != len(SERVICE_IDS):
        raise ValueError("service version tables must be unique")
    future_tables = set(ownership.table_migrators) - set(inventory.table_sources)
    if future_tables != set(created_table_owners):
        missing = sorted(future_tables - set(created_table_owners))
        undeclared = sorted(set(created_table_owners) - future_tables)
        raise ValueError(
            f"forward table declarations mismatch; missing={missing}, undeclared={undeclared}"
        )
    return adoptions
