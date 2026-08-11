"""Operator-owned executable codec artifacts for Core request and projection wires."""

from fdai_service_contracts import ConsumerCodec, ProducerCodec

CORE_REQUEST_PRODUCER_V1 = ProducerCodec("operator-core-request", "N-1", "1.0.0")
CORE_REQUEST_PRODUCER_V11 = ProducerCodec("operator-core-request", "N", "1.1.0")
CORE_REQUEST_PRODUCER_V12 = ProducerCodec("operator-core-request", "N", "1.2.0")
CORE_PROJECTION_CONSUMER_V1 = ConsumerCodec("core-operator-projection", "N-1", ("1.0.0",))
CORE_PROJECTION_CONSUMER_V11 = ConsumerCodec("core-operator-projection", "N", ("1.0.0", "1.1.0"))
CORE_PROJECTION_CONSUMER_V12 = ConsumerCodec(
    "core-operator-projection", "N", ("1.0.0", "1.1.0", "1.2.0")
)

__all__ = [
    "CORE_PROJECTION_CONSUMER_V1",
    "CORE_PROJECTION_CONSUMER_V11",
    "CORE_PROJECTION_CONSUMER_V12",
    "CORE_REQUEST_PRODUCER_V1",
    "CORE_REQUEST_PRODUCER_V11",
    "CORE_REQUEST_PRODUCER_V12",
]
