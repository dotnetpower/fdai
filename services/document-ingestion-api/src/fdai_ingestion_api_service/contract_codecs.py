"""Ingestion API codecs for durable activity and internal attachment handoff."""

from fdai_service_contracts import ConsumerCodec, ProducerCodec

CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_UNAVAILABLE = ConsumerCodec(
    "channel-attachment-admission", "N-1", ("0.0.0",)
)
CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_V1 = ConsumerCodec(
    "channel-attachment-admission", "N", ("0.0.0", "1.0.0")
)
CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_UNAVAILABLE = ProducerCodec(
    "channel-attachment-receipt", "N-1", "0.0.0"
)
CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_V1 = ProducerCodec("channel-attachment-receipt", "N", "1.0.0")

DOCUMENT_ACTIVITY_PRODUCER_V1 = ProducerCodec("document-ingestion-activity", "N-1", "1.0.0")
DOCUMENT_ACTIVITY_PRODUCER_V11 = ProducerCodec("document-ingestion-activity", "N", "1.1.0")

__all__ = [
    "CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_UNAVAILABLE",
    "CHANNEL_ATTACHMENT_ADMISSION_CONSUMER_V1",
    "CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_UNAVAILABLE",
    "CHANNEL_ATTACHMENT_RECEIPT_PRODUCER_V1",
    "DOCUMENT_ACTIVITY_PRODUCER_V1",
    "DOCUMENT_ACTIVITY_PRODUCER_V11",
]
