"""Dormant signed-manifest verification and replay reservation for Rule activation."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from fdai_service_contracts.rule_activation_manifest import (
    RuleActivationManifest,
    RuleActivationManifestExpectation,
    RuleActivationManifestTrust,
    SignedRuleActivationManifest,
    verify_rule_activation_manifest,
)

from fdai.shared.providers.state_store import StateStore

_PREFIX = "rule-activation:manifest-nonce:"


class RuleActivationManifestReplayError(RuntimeError):
    """Raised when a verified manifest nonce was already reserved."""


@dataclass(frozen=True, slots=True)
class RuleActivationManifestVerifier:
    """Verify and reserve a signed manifest without selecting an active generation."""

    trust: RuleActivationManifestTrust
    store: StateStore

    async def verify_and_reserve(
        self,
        envelope: SignedRuleActivationManifest,
        *,
        now: datetime,
        expected: RuleActivationManifestExpectation,
        consumed_nonces: Collection[str] = (),
    ) -> RuleActivationManifest:
        """Verify all trust inputs and reserve the nonce exactly once."""

        manifest = verify_rule_activation_manifest(
            envelope,
            trust=self.trust,
            now=now,
            expected=expected,
            consumed_nonces=consumed_nonces,
        )
        record = {
            "schema_version": "1.0.0",
            "manifest_digest": manifest.manifest_digest,
            "nonce": manifest.nonce,
            "release_id": manifest.release_id,
            "source": manifest.source.value,
            "deployment_scope_digest": manifest.deployment_scope_digest,
            "approval_authority": False,
            "activation_authority": False,
            "execution_authority": False,
        }
        key = _PREFIX + manifest.nonce
        if await self.store.write_state_if_absent(key, record):
            return manifest
        existing = await self.store.read_state(key)
        if existing == record:
            raise RuleActivationManifestReplayError("Rule activation manifest was already consumed")
        raise RuleActivationManifestReplayError(
            "Rule activation manifest nonce is bound to different content"
        )


__all__ = [
    "RuleActivationManifestReplayError",
    "RuleActivationManifestVerifier",
]
