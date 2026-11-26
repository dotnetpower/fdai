"""Canonical revision material and factory, re-exported by the adaptive contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fdai_service_contracts.ontology_query import content_digest

from fdai.core.rca.observation_history import HypothesisObservation, history_material

if TYPE_CHECKING:
    from .adaptive_contract import AdaptiveInvestigationDisposition, HypothesisRevisionSet


def build_hypothesis_revision_set(
    *,
    prior_active_set_receipt_digest: str,
    prior_frame_digest: str,
    observation_result_digest: str,
    scorer_version: str,
    graph_revision: str,
    evidence_cutoff: datetime,
    active_hypothesis_ids: tuple[str, ...],
    active_set_receipt_digest: str,
    evidence_refs: tuple[str, ...],
    complete: bool,
    truncated: bool,
    disposition: AdaptiveInvestigationDisposition,
    observation_history: tuple[HypothesisObservation, ...] = (),
) -> HypothesisRevisionSet:
    """Build a content-addressed revision without changing the legacy facade."""

    from .adaptive_contract import HypothesisRevisionSet

    canonical_ids = tuple(sorted(active_hypothesis_ids))
    canonical_refs = tuple(sorted(evidence_refs))
    material = {
        "prior_active_set_receipt_digest": prior_active_set_receipt_digest,
        "prior_frame_digest": prior_frame_digest,
        "observation_result_digest": observation_result_digest,
        "scorer_version": scorer_version,
        "graph_revision": graph_revision,
        "evidence_cutoff": evidence_cutoff.astimezone(UTC).isoformat(),
        "active_hypothesis_ids": canonical_ids,
        "active_set_receipt_digest": active_set_receipt_digest,
        "evidence_refs": canonical_refs,
        "complete": complete,
        "truncated": truncated,
        "disposition": disposition.value,
        "owner_agent": "Forseti",
        "execution_authority": False,
        **(
            {"observation_history": history_material(observation_history)}
            if observation_history
            else {}
        ),
    }
    return HypothesisRevisionSet(
        prior_active_set_receipt_digest=prior_active_set_receipt_digest,
        prior_frame_digest=prior_frame_digest,
        observation_result_digest=observation_result_digest,
        scorer_version=scorer_version,
        graph_revision=graph_revision,
        evidence_cutoff=evidence_cutoff,
        active_hypothesis_ids=canonical_ids,
        active_set_receipt_digest=active_set_receipt_digest,
        evidence_refs=canonical_refs,
        complete=complete,
        truncated=truncated,
        disposition=disposition,
        revision_digest=content_digest(material),
        observation_history=observation_history,
    )


def revision_material(revision: HypothesisRevisionSet) -> dict[str, object]:
    return {
        "prior_active_set_receipt_digest": revision.prior_active_set_receipt_digest,
        "prior_frame_digest": revision.prior_frame_digest,
        "observation_result_digest": revision.observation_result_digest,
        "scorer_version": revision.scorer_version,
        "graph_revision": revision.graph_revision,
        "evidence_cutoff": revision.evidence_cutoff.astimezone(UTC).isoformat(),
        "active_hypothesis_ids": revision.active_hypothesis_ids,
        "active_set_receipt_digest": revision.active_set_receipt_digest,
        "evidence_refs": revision.evidence_refs,
        "complete": revision.complete,
        "truncated": revision.truncated,
        "disposition": revision.disposition.value,
        "owner_agent": revision.owner_agent,
        "execution_authority": False,
        **(
            {"observation_history": history_material(revision.observation_history)}
            if revision.observation_history
            else {}
        ),
    }
