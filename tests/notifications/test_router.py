"""Unit tests for :class:`NotificationRouter`.

Coverage plan
-------------

- **matrix lookup** — a message with a known category lands on the
  matrix's primary channel.
- **unknown category → fallback route** — the router uses
  ``default_route`` and dispatches to *its* primary.
- **primary fails → fallback succeeds** — router advances through the
  fallback list in order and records both attempts.
- **all channels down → HIL escalate** — every attempted channel raises
  or returns ``delivered=False``; router calls
  :meth:`FakeHilEscalationSink.escalate` and audits with
  :attr:`RouteOutcome.ESCALATED_TO_HIL`.
- **trust-tier gate** — a channel whose ``trust_tiers`` does not include
  the message tier is skipped; if every channel skips, the router
  reports :attr:`RouteOutcome.TRUST_MISMATCH`.
- **audit is always written** — every terminal outcome appends exactly
  one entry to the state store.
"""

from __future__ import annotations

import pytest

from aiopspilot.core.notifications import (
    ChannelRegistry,
    MatrixValidationError,
    NotificationMatrix,
    NotificationRouter,
    OnAllFailAction,
    RouteOutcome,
    RouteSpec,
    load_matrix_from_mapping,
)
from aiopspilot.shared.providers.notifications import (
    NotificationMessage,
    Severity,
    TrustTier,
)
from aiopspilot.shared.providers.notifications.base import Link
from aiopspilot.shared.providers.testing.notifications import (
    FakeEmailChannel,
    FakeHilEscalationSink,
    FakePagerDutyChannel,
    FakeSlackChannel,
    FakeTeamsChannel,
    FakeWebhookChannel,
)
from aiopspilot.shared.providers.testing.state_store import InMemoryStateStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _matrix() -> NotificationMatrix:
    return load_matrix_from_mapping(
        {
            "matrix": {
                "version": 1,
                "default_route": "operational_alert",
                "routes": {
                    "hil_approval": {
                        "trust_tier": TrustTier.A1_HIL_APPROVAL.value,
                        "primary": "teams-hil-prd",
                        "fallback": ["slack-hil-prd"],
                        "on_all_fail": OnAllFailAction.HIL_ESCALATE.value,
                    },
                    "operational_alert": {
                        "trust_tier": TrustTier.A2_OPERATIONAL_ALERT.value,
                        "primary": "teams-ops-prd",
                        "fallback": ["pagerduty-primary", "email-oncall"],
                        "on_all_fail": OnAllFailAction.HIL_ESCALATE.value,
                    },
                    "digest_shadow_daily": {
                        "trust_tier": TrustTier.A4_DIGEST.value,
                        "primary": "teams-hil-prd",
                        "fallback": ["email-governance"],
                        "on_all_fail": OnAllFailAction.HIL_ESCALATE.value,
                    },
                },
            }
        }
    )


def _hil_message() -> NotificationMessage:
    return NotificationMessage(
        category="hil_approval",
        trust_tier=TrustTier.A1_HIL_APPROVAL,
        correlation_id="cid-hil-1",
        title="Approval needed: enforce promotion",
        body_markdown="Please review the pending action.",
        severity=Severity.WARN,
        audit_id="audit-hil-1",
        links=(Link(label="Review", url="https://example.com/pr/1"),),
    )


def _ops_message() -> NotificationMessage:
    return NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id="cid-ops-1",
        title="DLQ depth high",
        body_markdown="Depth = 42 (threshold 10).",
        severity=Severity.ERROR,
        audit_id="audit-ops-1",
    )


def _digest_message() -> NotificationMessage:
    return NotificationMessage(
        category="digest_shadow_daily",
        trust_tier=TrustTier.A4_DIGEST,
        correlation_id="cid-digest-1",
        title="Shadow accuracy: 96.4%",
        body_markdown="Report body.",
        severity=Severity.INFO,
    )


def _build_registry() -> tuple[
    ChannelRegistry,
    FakeTeamsChannel,
    FakeTeamsChannel,
    FakeSlackChannel,
    FakePagerDutyChannel,
    FakeEmailChannel,
    FakeEmailChannel,
]:
    teams_hil = FakeTeamsChannel(
        channel_id="teams-hil-prd",
        trust_tiers=frozenset(
            {
                TrustTier.A1_HIL_APPROVAL,
                TrustTier.A2_OPERATIONAL_ALERT,
                TrustTier.A3_CHAT_COMMAND,
                TrustTier.A4_DIGEST,
            }
        ),
    )
    teams_ops = FakeTeamsChannel(
        channel_id="teams-ops-prd",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    slack_hil = FakeSlackChannel(
        channel_id="slack-hil-prd",
        trust_tiers=frozenset({TrustTier.A1_HIL_APPROVAL, TrustTier.A3_CHAT_COMMAND}),
    )
    pd = FakePagerDutyChannel(
        channel_id="pagerduty-primary",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT}),
    )
    email_oncall = FakeEmailChannel(
        channel_id="email-oncall",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT, TrustTier.A4_DIGEST}),
    )
    email_gov = FakeEmailChannel(
        channel_id="email-governance",
        trust_tiers=frozenset({TrustTier.A2_OPERATIONAL_ALERT, TrustTier.A4_DIGEST}),
    )
    registry = ChannelRegistry(
        channels={
            teams_hil.channel_id: teams_hil,
            teams_ops.channel_id: teams_ops,
            slack_hil.channel_id: slack_hil,
            pd.channel_id: pd,
            email_oncall.channel_id: email_oncall,
            email_gov.channel_id: email_gov,
        }
    )
    return registry, teams_hil, teams_ops, slack_hil, pd, email_oncall, email_gov


def _build_router() -> tuple[
    NotificationRouter,
    ChannelRegistry,
    InMemoryStateStore,
    FakeHilEscalationSink,
    FakeTeamsChannel,
    FakeTeamsChannel,
    FakeSlackChannel,
    FakePagerDutyChannel,
    FakeEmailChannel,
    FakeEmailChannel,
]:
    audit = InMemoryStateStore()
    sink = FakeHilEscalationSink()
    registry, teams_hil, teams_ops, slack_hil, pd, email_oncall, email_gov = _build_registry()
    router = NotificationRouter(
        matrix=_matrix(),
        registry=registry,
        audit_store=audit,
        hil_sink=sink,
    )
    return (
        router,
        registry,
        audit,
        sink,
        teams_hil,
        teams_ops,
        slack_hil,
        pd,
        email_oncall,
        email_gov,
    )


# ---------------------------------------------------------------------------
# Matrix loader
# ---------------------------------------------------------------------------


class TestMatrixLoader:
    def test_missing_top_level_matrix_key_raises(self) -> None:
        with pytest.raises(MatrixValidationError):
            load_matrix_from_mapping({"other": {}})

    def test_missing_default_route_raises(self) -> None:
        with pytest.raises(MatrixValidationError):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "ghost",
                        "routes": {
                            "known": {
                                "trust_tier": "a2_operational_alert",
                                "primary": "channel-1",
                            }
                        },
                    }
                }
            )

    def test_bad_trust_tier_rejected(self) -> None:
        with pytest.raises(MatrixValidationError):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r1",
                        "routes": {
                            "r1": {
                                "trust_tier": "nonsense",
                                "primary": "channel-1",
                            }
                        },
                    }
                }
            )

    def test_bad_on_all_fail_rejected(self) -> None:
        with pytest.raises(MatrixValidationError):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r1",
                        "routes": {
                            "r1": {
                                "trust_tier": "a2_operational_alert",
                                "primary": "channel-1",
                                "on_all_fail": "silently_drop",
                            }
                        },
                    }
                }
            )

    def test_fallback_must_be_list_of_strings(self) -> None:
        with pytest.raises(MatrixValidationError):
            load_matrix_from_mapping(
                {
                    "matrix": {
                        "version": 1,
                        "default_route": "r1",
                        "routes": {
                            "r1": {
                                "trust_tier": "a2_operational_alert",
                                "primary": "channel-1",
                                "fallback": "channel-2",  # wrong shape
                            }
                        },
                    }
                }
            )

    def test_route_spec_channel_ids_prepends_primary(self) -> None:
        matrix = _matrix()
        route = matrix.routes["operational_alert"]
        assert route.channel_ids == ("teams-ops-prd", "pagerduty-primary", "email-oncall")

    def test_ships_default_yaml_matrix(self) -> None:
        # Sanity-check the shipped matrix parses cleanly.
        from pathlib import Path

        from aiopspilot.core.notifications import load_matrix_from_yaml

        repo_matrix = Path(__file__).resolve().parents[2] / "config" / "notifications-matrix.yaml"
        loaded = load_matrix_from_yaml(repo_matrix)
        assert "hil_approval" in loaded.routes
        assert loaded.routes["hil_approval"].trust_tier is TrustTier.A1_HIL_APPROVAL


# ---------------------------------------------------------------------------
# Router — happy paths
# ---------------------------------------------------------------------------


class TestRouterMatrixLookup:
    async def test_known_category_lands_on_primary(self) -> None:
        (
            router,
            _registry,
            audit,
            sink,
            teams_hil,
            _teams_ops,
            slack_hil,
            *_,
        ) = _build_router()

        result = await router.dispatch(_hil_message())

        assert result.outcome is RouteOutcome.DELIVERED
        assert result.delivered_channel_id == "teams-hil-prd"
        assert result.attempted_channel_ids == ("teams-hil-prd",)
        assert len(teams_hil.records) == 1
        assert len(slack_hil.records) == 0
        # No escalation happened.
        assert list(sink.entries) == []
        # Audit has one entry with outcome=delivered.
        entries = list(audit.audit_entries)
        assert len(entries) == 1
        assert entries[0]["entry"]["outcome"] == RouteOutcome.DELIVERED.value

    async def test_ops_alert_lands_on_teams_ops(self) -> None:
        (
            router,
            _registry,
            _audit,
            _sink,
            _teams_hil,
            teams_ops,
            *_,
        ) = _build_router()
        result = await router.dispatch(_ops_message())
        assert result.outcome is RouteOutcome.DELIVERED
        assert result.delivered_channel_id == "teams-ops-prd"
        assert len(teams_ops.records) == 1


# ---------------------------------------------------------------------------
# Router — unknown category falls back through default_route
# ---------------------------------------------------------------------------


class TestRouterUnknownCategory:
    async def test_unknown_category_uses_default_route(self) -> None:
        (
            router,
            _registry,
            _audit,
            _sink,
            _teams_hil,
            teams_ops,
            *_,
        ) = _build_router()

        message = NotificationMessage(
            category="never-defined-category",
            trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
            correlation_id="cid-unknown-1",
            title="Something",
            body_markdown="Body",
        )
        result = await router.dispatch(message)

        # default_route is operational_alert → primary teams-ops-prd.
        assert result.outcome is RouteOutcome.DELIVERED
        assert result.route.category == "operational_alert"
        assert result.delivered_channel_id == "teams-ops-prd"
        assert len(teams_ops.records) == 1


# ---------------------------------------------------------------------------
# Router — fallback chain
# ---------------------------------------------------------------------------


class TestRouterFallback:
    async def test_primary_raises_fallback_delivers(self) -> None:
        (
            router,
            _registry,
            audit,
            _sink,
            _teams_hil,
            teams_ops,
            _slack_hil,
            pd,
            _email_oncall,
            _email_gov,
        ) = _build_router()
        teams_ops.arm_raises(1)  # primary raises

        result = await router.dispatch(_ops_message())

        assert result.outcome is RouteOutcome.DELIVERED_ON_FALLBACK
        assert result.delivered_channel_id == "pagerduty-primary"
        assert result.attempted_channel_ids == ("teams-ops-prd", "pagerduty-primary")
        assert len(teams_ops.records) == 1  # was attempted
        assert len(pd.records) == 1
        entries = list(audit.audit_entries)
        assert entries[-1]["entry"]["outcome"] == RouteOutcome.DELIVERED_ON_FALLBACK.value

    async def test_primary_soft_fail_fallback_delivers(self) -> None:
        (
            router,
            _registry,
            _audit,
            _sink,
            _teams_hil,
            teams_ops,
            _slack_hil,
            pd,
            *_,
        ) = _build_router()
        teams_ops.arm_delivery_failures(1)  # returns delivered=False

        result = await router.dispatch(_ops_message())
        assert result.outcome is RouteOutcome.DELIVERED_ON_FALLBACK
        assert result.delivered_channel_id == "pagerduty-primary"
        # Two receipts: the failed one + the successful one.
        assert len(result.receipts) == 2
        assert result.receipts[0].delivered is False
        assert result.receipts[1].delivered is True
        assert len(pd.records) == 1

    async def test_walks_full_fallback_chain_in_order(self) -> None:
        (
            router,
            _registry,
            _audit,
            _sink,
            _teams_hil,
            teams_ops,
            _slack_hil,
            pd,
            email_oncall,
            _email_gov,
        ) = _build_router()
        teams_ops.arm_raises(1)
        pd.arm_delivery_failures(1)

        result = await router.dispatch(_ops_message())
        assert result.outcome is RouteOutcome.DELIVERED_ON_FALLBACK
        assert result.delivered_channel_id == "email-oncall"
        assert result.attempted_channel_ids == (
            "teams-ops-prd",
            "pagerduty-primary",
            "email-oncall",
        )
        assert len(email_oncall.records) == 1


# ---------------------------------------------------------------------------
# Router — all channels down → HIL escalate
# ---------------------------------------------------------------------------


class TestRouterAllChannelsDown:
    async def test_every_channel_raises_escalates_to_hil(self) -> None:
        (
            router,
            _registry,
            audit,
            sink,
            _teams_hil,
            teams_ops,
            _slack_hil,
            pd,
            email_oncall,
            *_,
        ) = _build_router()
        teams_ops.arm_raises(1)
        pd.arm_raises(1)
        email_oncall.arm_raises(1)

        result = await router.dispatch(_ops_message())

        assert result.outcome is RouteOutcome.ESCALATED_TO_HIL
        assert result.delivered_channel_id is None
        assert result.escalation_reason is not None
        entries = list(sink.entries)
        assert len(entries) == 1
        assert entries[0][0].category == "operational_alert"

        audit_entries = list(audit.audit_entries)
        assert audit_entries[-1]["entry"]["outcome"] == RouteOutcome.ESCALATED_TO_HIL.value
        assert audit_entries[-1]["entry"]["escalation_reason"] is not None

    async def test_every_channel_soft_fails_still_escalates(self) -> None:
        (
            router,
            _registry,
            _audit,
            sink,
            _teams_hil,
            teams_ops,
            _slack_hil,
            pd,
            email_oncall,
            *_,
        ) = _build_router()
        teams_ops.arm_delivery_failures(1)
        pd.arm_delivery_failures(1)
        email_oncall.arm_delivery_failures(1)

        result = await router.dispatch(_ops_message())
        assert result.outcome is RouteOutcome.ESCALATED_TO_HIL
        # All three receipts recorded, none delivered.
        assert len(result.receipts) == 3
        assert all(r.delivered is False for r in result.receipts)
        assert len(list(sink.entries)) == 1


# ---------------------------------------------------------------------------
# Router — trust-tier enforcement
# ---------------------------------------------------------------------------


class TestRouterTrustTier:
    async def test_channel_missing_tier_is_skipped(self) -> None:
        # Build a route where the primary channel does NOT accept A1
        # traffic; the router MUST skip and try the fallback.
        matrix = load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": TrustTier.A1_HIL_APPROVAL.value,
                            "primary": "teams-ops-prd",  # A2-only!
                            "fallback": ["slack-hil-prd"],
                        }
                    },
                }
            }
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        registry, _teams_hil, teams_ops, slack_hil, *_ = _build_registry()
        router = NotificationRouter(
            matrix=matrix,
            registry=registry,
            audit_store=audit,
            hil_sink=sink,
        )

        result = await router.dispatch(_hil_message())

        assert result.outcome is RouteOutcome.DELIVERED_ON_FALLBACK
        assert result.delivered_channel_id == "slack-hil-prd"
        # teams_ops was attempted but skipped without a call.
        assert len(teams_ops.records) == 0
        assert len(slack_hil.records) == 1

    async def test_all_channels_trust_mismatch_reports_specific_outcome(self) -> None:
        # Route with only A2-only channels, but the message is A1.
        matrix = load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": TrustTier.A1_HIL_APPROVAL.value,
                            "primary": "teams-ops-prd",
                            "fallback": ["pagerduty-primary"],
                        }
                    },
                }
            }
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        registry, *_ = _build_registry()
        router = NotificationRouter(
            matrix=matrix,
            registry=registry,
            audit_store=audit,
            hil_sink=sink,
        )

        result = await router.dispatch(_hil_message())
        assert result.outcome is RouteOutcome.TRUST_MISMATCH
        assert result.delivered_channel_id is None
        # Escalation still happened.
        assert len(list(sink.entries)) == 1


# ---------------------------------------------------------------------------
# Router — unresolved channel-id
# ---------------------------------------------------------------------------


class TestRouterUnresolvedChannel:
    async def test_all_channels_unresolved_reports_specific_outcome(self) -> None:
        matrix = load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": TrustTier.A1_HIL_APPROVAL.value,
                            "primary": "ghost-channel-1",
                            "fallback": ["ghost-channel-2"],
                        }
                    },
                }
            }
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        # Empty registry — no channel-ids resolve.
        router = NotificationRouter(
            matrix=matrix,
            registry=ChannelRegistry(),
            audit_store=audit,
            hil_sink=sink,
        )

        result = await router.dispatch(_hil_message())
        assert result.outcome is RouteOutcome.ROUTE_UNRESOLVED
        assert result.delivered_channel_id is None
        assert len(list(sink.entries)) == 1

    async def test_one_unresolved_falls_through_to_next(self) -> None:
        matrix = load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "hil_approval",
                    "routes": {
                        "hil_approval": {
                            "trust_tier": TrustTier.A1_HIL_APPROVAL.value,
                            "primary": "ghost-channel-1",
                            "fallback": ["teams-hil-prd"],
                        }
                    },
                }
            }
        )
        audit = InMemoryStateStore()
        sink = FakeHilEscalationSink()
        registry, teams_hil, *_ = _build_registry()
        router = NotificationRouter(
            matrix=matrix,
            registry=registry,
            audit_store=audit,
            hil_sink=sink,
        )
        result = await router.dispatch(_hil_message())
        assert result.outcome is RouteOutcome.DELIVERED_ON_FALLBACK
        assert result.delivered_channel_id == "teams-hil-prd"
        assert len(teams_hil.records) == 1


# ---------------------------------------------------------------------------
# Router — audit invariants
# ---------------------------------------------------------------------------


class TestRouterAudit:
    async def test_every_dispatch_writes_exactly_one_audit_entry(self) -> None:
        (
            router,
            _registry,
            audit,
            _sink,
            _teams_hil,
            _teams_ops,
            *_,
        ) = _build_router()
        for _ in range(5):
            await router.dispatch(_ops_message())
        assert len(list(audit.audit_entries)) == 5
        # Hash-chain intact.
        assert audit.verify_chain() is True

    async def test_audit_records_route_and_correlation(self) -> None:
        (
            router,
            _registry,
            audit,
            *_,
        ) = _build_router()
        await router.dispatch(_hil_message())
        entry = list(audit.audit_entries)[-1]["entry"]
        assert entry["action_kind"] == "notification.route"
        assert entry["category"] == "hil_approval"
        assert entry["trust_tier"] == TrustTier.A1_HIL_APPROVAL.value
        assert entry["correlation_id"] == "cid-hil-1"
        assert entry["audit_id"] == "audit-hil-1"
        assert entry["route_primary"] == "teams-hil-prd"


# ---------------------------------------------------------------------------
# Route spec defaults
# ---------------------------------------------------------------------------


class TestRouteSpecDefaults:
    def test_defaults_to_hil_escalate(self) -> None:
        spec = RouteSpec(
            category="x",
            trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
            primary="p",
        )
        assert spec.on_all_fail is OnAllFailAction.HIL_ESCALATE
        assert spec.fallback == ()
        assert spec.channel_ids == ("p",)


# ---------------------------------------------------------------------------
# Fake sanity — arm_delivery_failures / arm_raises input validation
# ---------------------------------------------------------------------------


class TestFakeChannelInputValidation:
    async def test_arm_delivery_failures_rejects_negative(self) -> None:
        fake = FakeWebhookChannel(channel_id="wh", trust_tiers=frozenset())
        with pytest.raises(ValueError):
            fake.arm_delivery_failures(-1)

    async def test_arm_raises_rejects_negative(self) -> None:
        fake = FakeWebhookChannel(channel_id="wh", trust_tiers=frozenset())
        with pytest.raises(ValueError):
            fake.arm_raises(-1)

    async def test_empty_tiers_frozenset_is_accept_any(self) -> None:
        # A channel with an empty tiers set MUST accept any tier — this
        # lets a lightweight test-only fake stay minimal.
        fake = FakeWebhookChannel(channel_id="wh", trust_tiers=frozenset())
        registry = ChannelRegistry(channels={fake.channel_id: fake})
        matrix = load_matrix_from_mapping(
            {
                "matrix": {
                    "version": 1,
                    "default_route": "r1",
                    "routes": {
                        "r1": {
                            "trust_tier": TrustTier.A2_OPERATIONAL_ALERT.value,
                            "primary": "wh",
                        }
                    },
                }
            }
        )
        router = NotificationRouter(
            matrix=matrix,
            registry=registry,
            audit_store=InMemoryStateStore(),
            hil_sink=FakeHilEscalationSink(),
        )
        result = await router.dispatch(_ops_message())
        assert result.outcome is RouteOutcome.DELIVERED
