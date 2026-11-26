"""Alert-private encoding bounds do not widen ontology queries or truncate evidence."""

import pytest

from fdai_service_contracts.alert_noise_content import (
    MAX_ALERT_RECORD_BYTES,
    MAX_ALERT_RECORD_NODES,
    canonical_alert_json,
    digest_alert_payload,
)
from fdai_service_contracts.ontology_query import content_digest


def test_small_record_digests_remain_exactly_compatible() -> None:
    payload = {"z": [False, None, 3], "a": {"b": 1.5}}
    assert digest_alert_payload(payload) == content_digest(payload)
    assert canonical_alert_json(payload) == '{"a":{"b":1.5},"z":[false,null,3]}'


def test_query_ceiling_stays_separate_from_private_alert_ceiling() -> None:
    payload = {"value": "x" * 70_000}
    assert digest_alert_payload(payload).startswith("sha256:")
    with pytest.raises(ValueError, match="65536"):
        content_digest(payload)


@pytest.mark.parametrize("payload", [{0: 1}, {"x": (1,)}, {"x": object()}, {"x": float("nan")}])
def test_noncanonical_payloads_are_rejected(payload: object) -> None:
    with pytest.raises(ValueError):
        digest_alert_payload(payload)


def test_no_byte_node_or_depth_overflow_is_truncated() -> None:
    deep: object = 0
    for _ in range(34):
        deep = [deep]
    for value in ({"x": "x" * MAX_ALERT_RECORD_BYTES}, [0] * MAX_ALERT_RECORD_NODES, deep):
        with pytest.raises(ValueError, match="bound"):
            digest_alert_payload(value)
