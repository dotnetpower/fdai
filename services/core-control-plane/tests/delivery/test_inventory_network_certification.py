"""Tests for isolated Azure inventory network certification reduction."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fdai.delivery.inventory_network_certification import (
    InventoryNetworkCampaignObservation,
    InventoryNetworkStage,
    _close_tls_writer,
    _receipt_private_ip,
    reduce_inventory_network_campaign,
)
from fdai.shared.providers.inventory_snapshot import (
    InventoryAttemptFailure,
    InventoryFailureCode,
)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _observation() -> InventoryNetworkCampaignObservation:
    return InventoryNetworkCampaignObservation(
        source_revision="a" * 40,
        request_id="inventory-network-" + ("b" * 48),
        recorded_at=datetime(2026, 9, 27, tzinfo=UTC),
        binding_digest=_digest("1"),
        token_digest=_digest("2"),
        management_dns_digest=_digest("3"),
        management_tls_digest=_digest("4"),
        postgres_dns_digest=_digest("5"),
        postgres_tls_digest=_digest("6"),
        blob_dns_digest=_digest("7"),
        blob_tls_digest=_digest("8"),
        baseline=InventoryNetworkStage(
            source="arg",
            generation_digest=_digest("9"),
            failures=(),
            active_during_failure_digest=None,
        ),
        fallback=InventoryNetworkStage(
            source="arm",
            generation_digest=_digest("a"),
            failures=(
                InventoryAttemptFailure(
                    code=InventoryFailureCode.DNS_FAILED,
                    message="primary source DNS was unavailable",
                ),
            ),
            active_during_failure_digest=_digest("9"),
        ),
        recovery=InventoryNetworkStage(
            source="arg",
            generation_digest=_digest("b"),
            failures=(),
            active_during_failure_digest=None,
        ),
        semantic_refresh={
            "schema_version": "fdai.semantic-graph-refresh-certification.v1",
            "evidence_statuses": [
                "complete",
                "conflicting",
                "incomplete",
                "stale",
                "unavailable",
            ],
            "provider_read_count": 1,
            "gateway_requery_count": 1,
            "audit_chain_verified": True,
            "write_through_digest": _digest("c"),
            "digest": _digest("d"),
            "observation_authority": False,
            "mutation_authority": False,
            "execution_authority": False,
        },
    )


def test_campaign_reducer_preserves_all_axes_and_zero_authority() -> None:
    receipt = reduce_inventory_network_campaign(_observation())

    assert [axis["name"] for axis in receipt["axes"]] == [
        "workload_token",
        "dns",
        "tcp_tls",
        "bounded_arg_query",
        "private_projection_write",
        "primary_unavailable_fallback",
        "higher_priority_recovery",
        "private_receipt_path",
    ]
    assert all(axis["status"] == "passed" for axis in receipt["axes"])
    assert receipt["source_sequence"] == ["arg", "arm", "arg"]
    assert receipt["semantic_refresh"]["provider_read_count"] == 1
    assert receipt["observation_authority"] is False
    assert receipt["mutation_authority"] is False
    assert receipt["execution_authority"] is False


@pytest.mark.parametrize(
    "observation",
    [
        replace(_observation(), fallback=replace(_observation().fallback, source="arg")),
        replace(
            _observation(),
            fallback=replace(
                _observation().fallback,
                active_during_failure_digest=_digest("0"),
            ),
        ),
        replace(_observation(), recovery=replace(_observation().recovery, source="arm")),
        replace(
            _observation(),
            fallback=replace(
                _observation().fallback,
                failures=(
                    InventoryAttemptFailure(
                        code=InventoryFailureCode.FORBIDDEN,
                        message="identity was forbidden",
                    ),
                ),
            ),
        ),
    ],
)
def test_campaign_reducer_rejects_unproven_fallback_or_recovery(
    observation: InventoryNetworkCampaignObservation,
) -> None:
    with pytest.raises(ValueError, match="fallback and recovery"):
        reduce_inventory_network_campaign(observation)


@pytest.mark.parametrize("value", ["", "8.8.8.8", "not-an-ip"])
def test_receipt_private_ip_rejects_missing_public_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="RECEIPT_PRIVATE_IP"):
        _receipt_private_ip({"FDAI_NETWORK_CERT_RECEIPT_PRIVATE_IP": value})


def test_receipt_private_ip_accepts_one_private_address() -> None:
    assert _receipt_private_ip({"FDAI_NETWORK_CERT_RECEIPT_PRIVATE_IP": "10.246.5.4"}) == (
        "10.246.5.4"
    )


async def test_tls_close_timeout_does_not_invalidate_a_completed_probe() -> None:
    class _Writer:
        closed = False

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            raise TimeoutError

    writer = _Writer()

    await _close_tls_writer(writer)  # type: ignore[arg-type]

    assert writer.closed is True
