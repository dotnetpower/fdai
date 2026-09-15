"""Compare material source and processing changes without confusing them with check clocks."""

from fdai_service_contracts.cloud_knowledge import CloudSourceEvidence
from fdai_service_contracts.cloud_knowledge_release import KnowledgeReleaseBinding
from fdai_service_contracts.cloud_knowledge_structure import CloudStructuredDocument


def source_update_pending(
    binding: KnowledgeReleaseBinding,
    source: CloudSourceEvidence,
    candidate: CloudSourceEvidence,
    structured: CloudStructuredDocument | None = None,
) -> bool:
    """A structured binding compares its own representation, never legacy normalized bytes.

    A check timestamp alone is not an update. Missing structured comparison data
    cannot certify unchanged processing and conservatively marks a candidate pending.
    """
    if (source.source_id, source.source_url) != (candidate.source_id, candidate.source_url):
        raise ValueError("cloud source checkpoint identity differs from admission")
    if source.source_sha256 != candidate.source_sha256:
        return True
    if binding.processing_digests:
        if structured is None:
            return True
        if (
            structured.evidence.source_id != candidate.source_id
            or structured.evidence.source_url != candidate.source_url
            or structured.evidence.source_sha256 != candidate.source_sha256
        ):
            raise ValueError("structured checkpoint does not match its raw source")
        candidate = structured.evidence
        index = next(
            (
                index
                for index, item in enumerate(binding.sources)
                if item.source_id == source.source_id
            ),
            None,
        )
        if index is None or binding.processing_digests[index] != structured.processing_digest:
            return True
    fields = ("source_sha256", "normalized_sha256", "applicability", "policy", "license_ref")
    return any(getattr(source, field) != getattr(candidate, field) for field in fields)
