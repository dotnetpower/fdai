"""Executor consumer and producer codecs for command and receipt wires."""

from fdai_service_contracts import ConsumerCodec, ProducerCodec

EXECUTOR_COMMAND_CONSUMER_V1 = ConsumerCodec("executor-command", "N-1", ("1.0.0",))
EXECUTOR_COMMAND_CONSUMER_V11 = ConsumerCodec("executor-command", "N", ("1.0.0",))
EXECUTOR_RECEIPT_PRODUCER_V1 = ProducerCodec("executor-receipt", "N-1", "1.0.0")
EXECUTOR_RECEIPT_PRODUCER_V11 = ProducerCodec("executor-receipt", "N", "1.1.0")

__all__ = [
    "EXECUTOR_COMMAND_CONSUMER_V1",
    "EXECUTOR_COMMAND_CONSUMER_V11",
    "EXECUTOR_RECEIPT_PRODUCER_V1",
    "EXECUTOR_RECEIPT_PRODUCER_V11",
]
