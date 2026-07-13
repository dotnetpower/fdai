"""Tests for deterministic manual freshness diff (delta + deletion tombstone)."""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill.freshness import (
    diff_snapshot,
    plan_retirements,
    snapshot_of,
)
from fdai.shared.providers.manual_source import ManualCandidate


def _cand(doc_id: str, sha: str) -> ManualCandidate:
    return ManualCandidate(doc_id=doc_id, source_ref=f"drop://{doc_id}", content_sha=sha)


def test_snapshot_records_ref_to_sha() -> None:
    snap = snapshot_of([_cand("a", "sha1"), _cand("b", "sha2")])
    assert snap == {"drop://a": "sha1", "drop://b": "sha2"}


def test_new_candidate_is_upserted() -> None:
    delta = diff_snapshot({}, [_cand("a", "sha1")])
    assert [c.doc_id for c in delta.upserted] == ["a"]
    assert delta.deleted == ()
    assert delta.unchanged == ()


def test_changed_sha_is_upserted_unchanged_is_skipped() -> None:
    previous = {"drop://a": "old", "drop://b": "same"}
    current = [_cand("a", "new"), _cand("b", "same")]
    delta = diff_snapshot(previous, current)
    assert [c.doc_id for c in delta.upserted] == ["a"]
    assert delta.unchanged == ("drop://b",)


def test_removed_source_ref_is_deleted() -> None:
    previous = {"drop://a": "sha1", "drop://gone": "sha9"}
    delta = diff_snapshot(previous, [_cand("a", "sha1")])
    assert delta.deleted == ("drop://gone",)
    assert delta.unchanged == ("drop://a",)


def test_empty_content_sha_always_reprocesses() -> None:
    previous = {"drop://a": ""}
    delta = diff_snapshot(previous, [_cand("a", "")])
    # Cannot confirm unchanged without a hash -> re-distill to stay safe.
    assert [c.doc_id for c in delta.upserted] == ["a"]
    assert delta.unchanged == ()


def test_diff_is_deterministically_ordered() -> None:
    previous = {"drop://z": "1", "drop://y": "2"}  # both deleted
    current = [_cand("b", "n"), _cand("a", "n")]  # both new
    delta = diff_snapshot(previous, current)
    assert [c.doc_id for c in delta.upserted] == ["a", "b"]
    assert delta.deleted == ("drop://y", "drop://z")


def test_plan_retirements_one_per_deletion() -> None:
    previous = {"drop://gone1": "1", "drop://gone2": "2", "drop://kept": "3"}
    delta = diff_snapshot(previous, [_cand("kept", "3")])
    retirements = plan_retirements(delta)
    assert [r.source_ref for r in retirements] == ["drop://gone1", "drop://gone2"]
    assert all(r.reason == "source manual removed" for r in retirements)


def test_no_deletions_plans_no_retirements() -> None:
    delta = diff_snapshot({"drop://a": "1"}, [_cand("a", "1")])
    assert plan_retirements(delta) == ()
