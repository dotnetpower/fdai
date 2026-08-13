"""Core-owned executable codec artifacts for every declared wire boundary."""

from fdai_service_contracts import ConsumerCodec, ProducerCodec

OPERATOR_REQUEST_CONSUMER_V1 = ConsumerCodec("operator-core-request", "N-1", ("1.0.0",))
OPERATOR_REQUEST_CONSUMER_V11 = ConsumerCodec("operator-core-request", "N", ("1.0.0", "1.1.0"))
OPERATOR_REQUEST_CONSUMER_V12 = ConsumerCodec(
    "operator-core-request", "N", ("1.0.0", "1.1.0", "1.2.0")
)
OPERATOR_REQUEST_CONSUMER_V13 = ConsumerCodec(
    "operator-core-request", "N", ("1.0.0", "1.1.0", "1.2.0", "1.3.0")
)
OPERATOR_PROJECTION_PRODUCER_V1 = ProducerCodec("core-operator-projection", "N-1", "1.0.0")
OPERATOR_PROJECTION_PRODUCER_V11 = ProducerCodec("core-operator-projection", "N", "1.1.0")
OPERATOR_PROJECTION_PRODUCER_V12 = ProducerCodec("core-operator-projection", "N", "1.2.0")
DOCUMENT_AUDIT_PRODUCER_V1 = ProducerCodec("document-worker-audit", "N-1", "1.0.0")
DOCUMENT_AUDIT_PRODUCER_V11 = ProducerCodec("document-worker-audit", "N", "1.0.0")
DOCUMENT_INDEX_PRODUCER_V1 = ProducerCodec("document-worker-index", "N-1", "1.0.0")
DOCUMENT_INDEX_PRODUCER_V11 = ProducerCodec("document-worker-index", "N", "1.0.0")
EXECUTOR_COMMAND_PRODUCER_V1 = ProducerCodec("executor-command", "N-1", "1.0.0")
EXECUTOR_COMMAND_PRODUCER_V11 = ProducerCodec("executor-command", "N", "1.0.0")
EXECUTOR_RECEIPT_CONSUMER_V1 = ConsumerCodec("executor-receipt", "N-1", ("1.0.0",))
EXECUTOR_RECEIPT_CONSUMER_V11 = ConsumerCodec("executor-receipt", "N", ("1.0.0", "1.1.0"))

__all__ = [name for name in globals() if name.endswith(("_V1", "_V11", "_V12", "_V13"))]
