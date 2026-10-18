"""Architecture-review composition for the Pantheon runtime."""

from __future__ import annotations

from pathlib import Path

import yaml

from fdai.core.architecture_review import (
    ArchitectureReviewProjector,
    OntologyArchitectureReviewLoop,
)
from fdai.delivery.persistence.state_store_architecture_review import (
    StateStoreArchitectureReviewStateStore,
)
from fdai.runtime.bootstrap_pantheon_models import PantheonInitialization


def build_architecture_review_loop(
    config: PantheonInitialization,
    *,
    asset_root: Path,
) -> OntologyArchitectureReviewLoop | None:
    """Build the optional observation-only architecture-review loop."""

    sources = config.container.architecture_review_sources
    if sources is None:
        return None
    ontology_store = config.control_loop.ontology_instance_store
    if ontology_store is None:
        raise RuntimeError("architecture review sources require an ontology instance store")
    manifest_path = asset_root / "config" / "architecture-review.yaml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError("architecture review manifest is unavailable") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("architecture review manifest MUST contain a mapping")
    return OntologyArchitectureReviewLoop(
        context_source=sources.context,
        evidence_source=sources.evidence,
        state_store=StateStoreArchitectureReviewStateStore(config.incident_audit_store),
        observation_sink=ArchitectureReviewProjector(ontology_store, manifest),
    )


__all__ = ["build_architecture_review_loop"]
