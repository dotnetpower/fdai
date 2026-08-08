"""Document Worker consumer codecs for activity, audit, and index wires."""

from fdai_service_contracts import ConsumerCodec

DOCUMENT_ACTIVITY_CONSUMER_V1 = ConsumerCodec("document-ingestion-activity", "N-1", ("1.0.0",))
DOCUMENT_ACTIVITY_CONSUMER_V11 = ConsumerCodec(
    "document-ingestion-activity", "N", ("1.0.0", "1.1.0")
)
DOCUMENT_AUDIT_CONSUMER_V1 = ConsumerCodec("document-worker-audit", "N-1", ("1.0.0",))
DOCUMENT_AUDIT_CONSUMER_V11 = ConsumerCodec("document-worker-audit", "N", ("1.0.0",))
DOCUMENT_INDEX_CONSUMER_V1 = ConsumerCodec("document-worker-index", "N-1", ("1.0.0",))
DOCUMENT_INDEX_CONSUMER_V11 = ConsumerCodec("document-worker-index", "N", ("1.0.0",))

__all__ = [name for name in globals() if name.endswith(("_V1", "_V11"))]
