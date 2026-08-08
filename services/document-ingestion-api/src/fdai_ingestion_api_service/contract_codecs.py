"""Ingestion API producer codecs for durable document activity."""

from fdai_service_contracts import ProducerCodec

DOCUMENT_ACTIVITY_PRODUCER_V1 = ProducerCodec("document-ingestion-activity", "N-1", "1.0.0")
DOCUMENT_ACTIVITY_PRODUCER_V11 = ProducerCodec("document-ingestion-activity", "N", "1.1.0")

__all__ = ["DOCUMENT_ACTIVITY_PRODUCER_V1", "DOCUMENT_ACTIVITY_PRODUCER_V11"]
