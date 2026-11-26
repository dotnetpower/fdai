"""Deterministic event-to-action and action-risk bindings for Forseti."""

from __future__ import annotations

RULE_MATCH: dict[str, str] = {
    "public_network_enabled": "remediate.disable-public-access",
    "unencrypted_disk": "remediate.enable-encryption",
    "restart_needed": "ops.restart-service",
    "chaos_experiment_request": "ops.restart-service",
    "control_plane.t2_proposer_failure": "ops.switch-t2-proposer-route",
    "preflight_toggle_blocker": "remediate.apply-preflight-toggle",
}

RISK_VERDICT: dict[str, str] = {
    "remediate.disable-public-access": "auto",
    "remediate.enable-encryption": "hil",
    "ops.restart-service": "auto",
    "governance.notify-admin-privilege-violation": "auto",
    "ops.failover-primary": "hil",
    "ops.switch-t2-proposer-route": "hil",
    "remediate.delete-storage": "deny",
    "remediate.apply-preflight-toggle": "hil",
}


__all__ = ["RISK_VERDICT", "RULE_MATCH"]
