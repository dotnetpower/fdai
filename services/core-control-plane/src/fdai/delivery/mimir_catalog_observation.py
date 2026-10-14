"""Retain Mimir's exact active Rule generation observation without promotion authority."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.ontology_query import content_digest

from fdai.agents import MimirRuleSourcePollResult
from fdai.core.tiers.t0_deterministic import RuleGenerationSnapshot
from fdai.shared.providers.state_store import StateStore

_KEY = "pantheon/mimir/active-rule-generation-observation"
_ARTIFACT_PREFIX = "pantheon/mimir/rule-source-observation/"
_MAX_RETAINED_OBSERVATIONS = 1_000


class ActiveRuleGenerationReader(Protocol):
    async def rule_generation_snapshot(self) -> RuleGenerationSnapshot: ...


class MimirActiveCatalogPoller:
    """Observe one authoritative active membership source; never infer regression or promotion."""

    def __init__(self, *, reader: ActiveRuleGenerationReader, store: StateStore) -> None:
        self._reader = reader
        self._store = store

    async def poll_rule_sources(self, *, limit: int, now: datetime) -> MimirRuleSourcePollResult:
        if type(limit) is not int or limit < 1 or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Rule source observation requires a bounded aware request")
        snapshot = await self._reader.rule_generation_snapshot()
        digest = snapshot.generation_digest
        if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
            raise ValueError("active Rule generation is unavailable")
        ids = sorted(rule.id for rule in snapshot.rules)
        if len(ids) != len(set(ids)):
            raise ValueError("active Rule generation has duplicate membership")
        record = {
            "schema_version": "1.0.0",
            "generation_digest": digest,
            "membership_digest": content_digest(ids),
            "rule_count": len(ids),
            "recorded_at": now.isoformat(),
            "execution_authority": False,
        }
        record_digest = content_digest(record)
        artifact_key = _ARTIFACT_PREFIX + record_digest
        audit = {
            "action_kind": "mimir.rule-source.observed",
            "principal": "Mimir",
            "generation_digest": digest,
            "evidence_ref": "rule-source:" + record_digest,
            "execution_authority": False,
        }
        await self._store.write_state_with_audit_if_absent(artifact_key, record, audit)
        if await self._store.read_state(artifact_key) != record:
            raise ValueError("Rule source observation record conflicts")
        await self._store.delete_states_beyond(
            _ARTIFACT_PREFIX, retain_newest=_MAX_RETAINED_OBSERVATIONS
        )
        for _attempt in range(4):
            previous = await self._store.read_state(_KEY)
            if previous is None:
                if await self._store.write_state_if_absent(_KEY, {**record, "revision": 1}):
                    return MimirRuleSourcePollResult(1, 0, "rule-source:" + record_digest)
                continue
            if (
                set(previous) != set(record) | {"revision"}
                or previous.get("schema_version") != "1.0.0"
                or type(previous.get("revision")) is not int
                or not 1 <= previous["revision"] < 2**63 - 1
                or not isinstance(previous.get("generation_digest"), str)
                or re.fullmatch(r"[a-f0-9]{64}", previous["generation_digest"]) is None
                or not isinstance(previous.get("membership_digest"), str)
                or re.fullmatch(r"sha256:[a-f0-9]{64}", previous["membership_digest"]) is None
                or type(previous.get("rule_count")) is not int
                or previous["rule_count"] < 0
                or previous.get("execution_authority") is not False
            ):
                raise ValueError("retained Rule observation is malformed")
            changed = previous["generation_digest"] != digest
            if not changed:
                if previous.get("membership_digest") != record["membership_digest"]:
                    raise ValueError("active Rule generation membership changed without its digest")
                return MimirRuleSourcePollResult(1, 0, "rule-source:" + record_digest)
            current = await self._reader.rule_generation_snapshot()
            if current.generation_digest != digest:
                raise ValueError("active Rule generation changed during observation")
            if await self._store.compare_and_set_state(
                _KEY,
                {**record, "revision": previous["revision"] + 1},
                expected_revision=previous["revision"],
            ):
                return MimirRuleSourcePollResult(1, 1, "rule-source:" + record_digest)
        raise RuntimeError("Rule observation CAS bound exceeded")
