"""Core-owned alert codecs; unavailable artifacts classify old peers only."""

from fdai_service_contracts.alert_noise_codec import AlertConsumerCodec, AlertProducerCodec

COMMAND_CONSUMER_UNAVAILABLE = AlertConsumerCodec("alert-noise-command", "N-1", ("0.0.0",))
COMMAND_CONSUMER_V1 = AlertConsumerCodec("alert-noise-command", "N", ("0.0.0", "1.0.0"))
RESULT_PRODUCER_UNAVAILABLE = AlertProducerCodec("alert-noise-result", "N-1", "0.0.0")
RESULT_PRODUCER_V1 = AlertProducerCodec("alert-noise-result", "N", "1.0.0")
READINESS_PRODUCER_UNAVAILABLE = AlertProducerCodec("alert-noise-readiness", "N-1", "0.0.0")
READINESS_PRODUCER_V1 = AlertProducerCodec("alert-noise-readiness", "N", "1.0.0")
