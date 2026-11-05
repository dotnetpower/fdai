from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.shared.providers.cost_governance_campaign import CostCampaignEpisode
from fdai.shared.providers.cost_governance_lifecycle import CostRevisionPin

import fdai_cost_governance.campaign_import as campaign_import
from fdai_cost_governance.campaign_import import (
    CostCampaignImportConflictError,
    CostCampaignImportContext,
    _boolean,
    _canonical_digest,
    _integer,
    _load_json,
    _string_tuple,
    _text,
    _timestamp,
    import_cost_campaign_observations,
    load_cost_campaign_import_policy,
    load_cost_campaign_observation_batch,
)

_NOW = datetime(2026, 9, 12, tzinfo=UTC)
_POLICY = Path(__file__).resolve().parents[3] / "config/cost-governance-w7-policy.json"
_TARGETS = frozenset({"remediate.right-size", "cost-aware-remediation"})


class _Store:
    def __init__(self) -> None:
        self.episodes: list[CostCampaignEpisode] = []

    async def read_cost_campaign_episodes(
        self,
        campaign_id: str,
        revision_pin_digest: str,
        *,
        limit: int,
    ) -> tuple[CostCampaignEpisode, ...]:
        return tuple(
            item
            for item in self.episodes[:limit]
            if item.campaign_id == campaign_id and item.revision_pin_digest == revision_pin_digest
        )

    async def append_cost_campaign_episode(
        self,
        episode: CostCampaignEpisode,
        *,
        expected_revision: int,
    ) -> bool:
        if expected_revision != 0 or any(
            item.episode_id == episode.episode_id for item in self.episodes
        ):
            return False
        self.episodes.append(episode)
        return True


def _pin() -> CostRevisionPin:
    return CostRevisionPin(
        package_id="cost-governance",
        package_version="0.1.1",
        source_revision="a" * 40,
        wheel_digest=f"sha256:{'b' * 64}",
        image_digest=f"sha256:{'c' * 64}",
        asset_manifest_digest=f"sha256:{'d' * 64}",
        semantic_profile_digest=f"sha256:{'e' * 64}",
        ontology_release_digest=f"sha256:{'f' * 64}",
        runtime_config_digest=f"sha256:{'0' * 64}",
        activation_revision=2,
    )


def _context() -> CostCampaignImportContext:
    return CostCampaignImportContext(
        source_workflow_path=".github/workflows/cost-governance-observation-export.yml",
        source_run_id=42,
        source_run_attempt=1,
        source_artifact_name="cost-governance-observations-campaign-001",
        imported_at=_NOW,
    )


def _observation() -> dict[str, object]:
    return {
        "audit_complete": True,
        "decision_correct": True,
        "effect_path_complete": True,
        "episode_id": "episode-001",
        "evidence_refs": ["audit:episode-001", "observer:episode-001"],
        "hard_dependencies_complete": True,
        "objective_regression": False,
        "observed_at": (_NOW - timedelta(days=1)).isoformat(),
        "ontology_competency_passed": True,
        "outcome": "no-op",
        "parity_explained": True,
        "policy_escape": False,
        "policy_excluded": False,
        "protected_objectives_complete": True,
        "reason": "verified.no-op",
        "recovery_attempts": 0,
        "rollback_evidence_complete": True,
        "safeguards_complete": True,
        "settlement_statuses": [],
        "target_refs": ["remediate.right-size", "cost-aware-remediation"],
        "topic_owner_correct": True,
        "unauthorized_disclosure": False,
    }


def _batch(tmp_path: Path, observation: dict[str, object] | None = None) -> Path:
    body = {
        "campaign_id": "campaign-001",
        "observations": [observation or _observation()],
        "revision_pin_digest": _pin().digest,
        "schema_version": "1.0.0",
    }
    path = tmp_path / "cost-governance-observation-batch.json"
    path.write_text(
        json.dumps({**body, "batch_digest": _canonical_digest(body)}, sort_keys=True),
        encoding="utf-8",
    )
    return path


async def test_import_assigns_live_trust_and_is_idempotent(tmp_path: Path) -> None:
    policy = load_cost_campaign_import_policy(_POLICY)
    batch = load_cost_campaign_observation_batch(
        _batch(tmp_path),
        maximum_episodes=policy.maximum_batch_episodes,
    )
    store = _Store()

    first = await import_cost_campaign_observations(
        batch,
        revision_pin=_pin(),
        context=_context(),
        policy=policy,
        allowed_target_ids=_TARGETS,
        store=store,
    )
    second = await import_cost_campaign_observations(
        batch,
        revision_pin=_pin(),
        context=_context(),
        policy=policy,
        allowed_target_ids=_TARGETS,
        store=store,
    )

    assert set(first.to_mapping()) == {
        "accepted_count",
        "batch_digest",
        "campaign_id",
        "duplicate_count",
    }
    assert (first.accepted_count, first.duplicate_count) == (1, 0)
    assert (second.accepted_count, second.duplicate_count) == (0, 1)
    assert store.episodes[0].evidence_kind.value == "live-authoritative"
    assert store.episodes[0].revision_pin_digest == _pin().digest
    assert store.episodes[0].retention_until == (
        store.episodes[0].observed_at + timedelta(days=policy.retention_days)
    )


async def test_import_is_stable_across_trusted_reexport_runs(tmp_path: Path) -> None:
    policy = load_cost_campaign_import_policy(_POLICY)
    batch = load_cost_campaign_observation_batch(
        _batch(tmp_path),
        maximum_episodes=policy.maximum_batch_episodes,
    )
    store = _Store()

    await import_cost_campaign_observations(
        batch,
        revision_pin=_pin(),
        context=_context(),
        policy=policy,
        allowed_target_ids=_TARGETS,
        store=store,
    )
    replay = await import_cost_campaign_observations(
        batch,
        revision_pin=_pin(),
        context=replace(
            _context(),
            source_run_id=43,
            source_run_attempt=2,
            imported_at=_NOW + timedelta(hours=1),
        ),
        policy=policy,
        allowed_target_ids=_TARGETS,
        store=store,
    )

    assert (replay.accepted_count, replay.duplicate_count) == (0, 1)


async def test_import_rejects_excess_source_evidence_refs(tmp_path: Path) -> None:
    policy = load_cost_campaign_import_policy(_POLICY)
    observation = {
        **_observation(),
        "evidence_refs": [f"audit:{index}" for index in range(61)],
    }
    batch = load_cost_campaign_observation_batch(
        _batch(tmp_path, observation),
        maximum_episodes=policy.maximum_batch_episodes,
    )

    with pytest.raises(ValueError, match="1..60 unique"):
        await import_cost_campaign_observations(
            batch,
            revision_pin=_pin(),
            context=_context(),
            policy=policy,
            allowed_target_ids=_TARGETS,
            store=_Store(),
        )


def test_batch_cannot_declare_its_own_evidence_kind(tmp_path: Path) -> None:
    observation = {**_observation(), "evidence_kind": "live-authoritative"}
    policy = load_cost_campaign_import_policy(_POLICY)

    with pytest.raises(ValueError, match="observation fields"):
        load_cost_campaign_observation_batch(
            _batch(tmp_path, observation),
            maximum_episodes=policy.maximum_batch_episodes,
        )


def test_batch_rejects_truncated_revision_pin_digest(tmp_path: Path) -> None:
    path = _batch(tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["revision_pin_digest"] = "sha256:a"
    body = {key: value for key, value in document.items() if key != "batch_digest"}
    document["batch_digest"] = _canonical_digest(body)
    path.write_text(json.dumps(document), encoding="utf-8")
    policy = load_cost_campaign_import_policy(_POLICY)

    with pytest.raises(ValueError, match="revision_pin_digest"):
        load_cost_campaign_observation_batch(
            path,
            maximum_episodes=policy.maximum_batch_episodes,
        )


async def test_import_rejects_unapproved_source_and_conflicting_replay(tmp_path: Path) -> None:
    policy = load_cost_campaign_import_policy(_POLICY)
    batch = load_cost_campaign_observation_batch(
        _batch(tmp_path),
        maximum_episodes=policy.maximum_batch_episodes,
    )
    store = _Store()
    with pytest.raises(ValueError, match="not authorized"):
        await import_cost_campaign_observations(
            batch,
            revision_pin=_pin(),
            context=replace(_context(), source_workflow_path=".github/workflows/other.yml"),
            policy=policy,
            allowed_target_ids=_TARGETS,
            store=store,
        )

    await import_cost_campaign_observations(
        batch,
        revision_pin=_pin(),
        context=_context(),
        policy=policy,
        allowed_target_ids=_TARGETS,
        store=store,
    )
    changed = replace(store.episodes[0], decision_correct=False)
    store.episodes[0] = changed
    with pytest.raises(CostCampaignImportConflictError, match="different evidence"):
        await import_cost_campaign_observations(
            batch,
            revision_pin=_pin(),
            context=_context(),
            policy=policy,
            allowed_target_ids=_TARGETS,
            store=store,
        )


async def test_import_rejects_out_of_window_observation(tmp_path: Path) -> None:
    observation = {
        **_observation(),
        "observed_at": (_NOW - timedelta(days=91)).isoformat(),
    }
    policy = load_cost_campaign_import_policy(_POLICY)
    batch = load_cost_campaign_observation_batch(
        _batch(tmp_path, observation),
        maximum_episodes=policy.maximum_batch_episodes,
    )

    with pytest.raises(ValueError, match="outside the import window"):
        await import_cost_campaign_observations(
            batch,
            revision_pin=_pin(),
            context=_context(),
            policy=policy,
            allowed_target_ids=_TARGETS,
            store=_Store(),
        )


async def test_campaign_import_validation_and_conflict_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="workflow path is invalid"):
        replace(_context(), source_workflow_path="bad.yml")
    with pytest.raises(ValueError, match="run identity MUST be positive"):
        replace(_context(), source_run_id=0)
    with pytest.raises(ValueError, match="artifact name is invalid"):
        replace(_context(), source_artifact_name="bad")
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(_context(), imported_at=datetime(2026, 9, 12))

    bad_pol = tmp_path / "bad_pol.json"
    bad_pol.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="policy fields are invalid"):
        load_cost_campaign_import_policy(bad_pol)

    pol_doc = json.loads(_POLICY.read_text(encoding="utf-8"))
    bad_wf_pol = tmp_path / "bad_wf.json"
    bad_wf_pol.write_text(
        json.dumps({**pol_doc, "allowed_exporter_workflow_paths": ["bad"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="workflow allowlist is invalid"):
        load_cost_campaign_import_policy(bad_wf_pol)

    for doc_override, match in (
        ({"extra": 1}, "batch fields are invalid"),
        ({"schema_version": "2.0.0"}, "schema_version MUST be 1.0.0"),
        ({"campaign_id": "BAD_ID"}, "campaign_id is invalid"),
        ({"observations": []}, "exceed the configured bound"),
        ({"observations": [_observation(), _observation()]}, "episode ids MUST be unique"),
    ):
        base_doc = json.loads(_batch(tmp_path).read_text(encoding="utf-8"))
        base_doc.pop("batch_digest")
        base_doc.update(doc_override)
        p = tmp_path / "custom_batch.json"
        p.write_text(
            json.dumps({**base_doc, "batch_digest": _canonical_digest(base_doc)}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=match):
            load_cost_campaign_observation_batch(p, maximum_episodes=10)

    bad_digest_path = _batch(tmp_path)
    bad_digest_doc = json.loads(bad_digest_path.read_text(encoding="utf-8"))
    bad_digest_doc["batch_digest"] = f"sha256:{'0' * 64}"
    bad_digest_path.write_text(json.dumps(bad_digest_doc), encoding="utf-8")
    with pytest.raises(ValueError, match="batch digest does not match"):
        load_cost_campaign_observation_batch(bad_digest_path, maximum_episodes=10)

    policy = load_cost_campaign_import_policy(_POLICY)
    valid_batch = load_cost_campaign_observation_batch(_batch(tmp_path), maximum_episodes=10)

    with pytest.raises(ValueError, match="revision pin does not match"):
        await import_cost_campaign_observations(
            valid_batch,
            revision_pin=replace(_pin(), activation_revision=99),
            context=_context(),
            policy=policy,
            allowed_target_ids=_TARGETS,
            store=_Store(),
        )

    with pytest.raises(ValueError, match="not package-owned"):
        await import_cost_campaign_observations(
            valid_batch,
            revision_pin=_pin(),
            context=_context(),
            policy=policy,
            allowed_target_ids=frozenset({"other.target"}),
            store=_Store(),
        )

    class _RejectStore(_Store):
        async def append_cost_campaign_episode(
            self,
            episode: CostCampaignEpisode,
            *,
            expected_revision: int,
        ) -> bool:
            return False

    with pytest.raises(CostCampaignImportConflictError, match="append conflicted"):
        await import_cost_campaign_observations(
            valid_batch,
            revision_pin=_pin(),
            context=_context(),
            policy=policy,
            allowed_target_ids=_TARGETS,
            store=_RejectStore(),
        )

    monkeypatch.setattr(campaign_import, "_MAX_CAMPAIGN_EPISODES", 0)
    with pytest.raises(ValueError, match="retained episode bound"):
        await import_cost_campaign_observations(
            valid_batch,
            revision_pin=_pin(),
            context=_context(),
            policy=policy,
            allowed_target_ids=_TARGETS,
            store=_Store(),
        )

    with pytest.raises(ValueError, match="unavailable or exceeds"):
        _load_json(tmp_path / "missing.json", maximum_bytes=100, label="doc")
    arr_path = tmp_path / "arr.json"
    arr_path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="MUST contain an object"):
        _load_json(arr_path, maximum_bytes=100, label="doc")
    dup_path = tmp_path / "dup.json"
    dup_path.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(ValueError, match="repeats key"):
        _load_json(dup_path, maximum_bytes=100, label="doc")

    with pytest.raises(ValueError, match="bounded non-empty ASCII"):
        _text({"k": ""}, "k", 10)
    with pytest.raises(ValueError, match="MUST be an integer"):
        _integer({"k": True}, "k", 0, 10)
    with pytest.raises(ValueError, match="MUST be a boolean"):
        _boolean({"k": "yes"}, "k")
    with pytest.raises(ValueError, match="bounded ASCII string array"):
        _string_tuple([""], "refs")
    with pytest.raises(ValueError, match="MUST be RFC3339"):
        _timestamp(123)
    with pytest.raises(ValueError, match="MUST be RFC3339"):
        _timestamp("bad")
    with pytest.raises(ValueError, match="MUST include a timezone"):
        _timestamp("2026-09-12T00:00:00")
