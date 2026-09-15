"""Operator-owned alert codecs; no decoding result grants readiness or authority."""

from fdai_service_contracts.alert_noise_codec import AlertConsumerCodec, AlertProducerCodec

COMMAND_PRODUCER_UNAVAILABLE = AlertProducerCodec("alert-noise-command", "N-1", "0.0.0")
COMMAND_PRODUCER_V1 = AlertProducerCodec("alert-noise-command", "N", "1.0.0")
RESULT_CONSUMER_UNAVAILABLE = AlertConsumerCodec("alert-noise-result", "N-1", ("0.0.0",))
RESULT_CONSUMER_V1 = AlertConsumerCodec("alert-noise-result", "N", ("0.0.0", "1.0.0"))
READINESS_CONSUMER_UNAVAILABLE = AlertConsumerCodec("alert-noise-readiness", "N-1", ("0.0.0",))
READINESS_CONSUMER_V1 = AlertConsumerCodec("alert-noise-readiness", "N", ("0.0.0", "1.0.0"))
