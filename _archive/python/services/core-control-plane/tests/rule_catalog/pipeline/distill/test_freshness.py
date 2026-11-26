"""Tests for deterministic manual freshness diff (delta + deletion tombstone)."""

from __future__ import annotations

from fdai.rule_catalog.pipeline.distill.freshness import (
    diff_snapshot,
    plan_retirements,
    snapshot_of,
)
from fdai.shared.providers.manual_source import ManualCandidate


def _cand(
    doc_id: str,
    sha: str,
    *,
    labels: tuple[str, ...] = (),
    space: str = "",
    verified: bool = False,
    view_count: int = 0,
) -> ManualCandidate:
    return ManualCandidate(
        doc_id=doc_id,
        source_ref=f"drop://{doc_id}",
        content_sha=sha,
        labels=labels,
        space=space,
        verified=verified,
        view_count=view_count,
    )


def test_snapshot_keys_on_source_ref_with_stable_fingerprint() -> None:
    snap = snapshot_of([_cand("a", "sha1"), _cand("b", "sha2")])
    assert set(snap) == {"drop://a", "drop://b"}
    assert snap == snapshot_of([_cand("a", "sha1"), _cand("b", "sha2")])  # stable
    assert snap["drop://a"] != snap["drop://b"]  # content-sensitive


def test_new_candidate_is_upserted() -> None:
    delta = diff_snapshot({}, [_cand("a", "sha1")])
    assert [c.doc_id for c in delta.upserted] == ["a"]
    assert delta.deleted == ()
    assert delta.unchanged == ()


def test_changed_sha_is_upserted_unchanged_is_skipped() -> None:
    previous = snapshot_of([_cand("a", "old"), _cand("b", "same")])
    current = [_cand("a", "new"), _cand("b", "same")]
    delta = diff_snapshot(previous, current)
    assert [c.doc_id for c in delta.upserted] == ["a"]
    assert delta.unchanged == ("drop://b",)


def test_label_change_reprocesses_despite_identical_content() -> None:
    previous = snapshot_of([_cand("a", "same")])
    delta = diff_snapshot(previous, [_cand("a", "same", labels=("runbook",))])
    assert [c.doc_id for c in delta.upserted] == ["a"]  # relabel -> re-triage


def test_verified_flip_reprocesses() -> None:
    previous = snapshot_of([_cand("a", "same")])
    delta = diff_snapshot(previous, [_cand("a", "same", verified=True)])
    assert [c.doc_id for c in delta.upserted] == ["a"]


def test_space_change_reprocesses() -> None:
    previous = snapshot_of([_cand("a", "same", space="old")])
    delta = diff_snapshot(previous, [_cand("a", "same", space="new")])
    assert [c.doc_id for c in delta.upserted] == ["a"]


def test_view_count_change_alone_does_not_reprocess() -> None:
    # High-churn signal excluded from the fingerprint: ordinary traffic must not
    # force a needless re-distill.
    previous = snapshot_of([_cand("a", "same", view_count=10)])
    delta = diff_snapshot(previous, [_cand("a", "same", view_count=9999)])
    assert delta.upserted == ()
    assert delta.unchanged == ("drop://a",)


def test_removed_source_ref_is_deleted() -> None:
    previous = snapshot_of([_cand("a", "sha1"), _cand("gone", "sha9")])
    delta = diff_snapshot(previous, [_cand("a", "sha1")])
    assert delta.deleted == ("drop://gone",)
    assert delta.unchanged == ("drop://a",)


def test_empty_content_sha_always_reprocesses() -> None:
    previous = snapshot_of([_cand("a", "")])
    delta = diff_snapshot(previous, [_cand("a", "")])
    # Cannot confirm unchanged without a hash -> re-distill to stay safe.
    assert [c.doc_id for c in delta.upserted] == ["a"]
    assert delta.unchanged == ()


def test_legacy_content_sha_snapshot_reprocesses_once() -> None:
    # A snapshot written by an older build holds bare content_sha values; they
    # mismatch the new fingerprint once, so the manual re-distills on upgrade
    # and stabilises after.
    legacy = {"drop://a": "same"}
    assert [c.doc_id for c in diff_snapshot(legacy, [_cand("a", "same")]).upserted] == ["a"]
    fresh = snapshot_of([_cand("a", "same")])
    assert diff_snapshot(fresh, [_cand("a", "same")]).unchanged == ("drop://a",)


def test_diff_is_deterministically_ordered() -> None:
    previous = snapshot_of([_cand("z", "1"), _cand("y", "2")])  # both deleted
    current = [_cand("b", "n"), _cand("a", "n")]  # both new
    delta = diff_snapshot(previous, current)
    assert [c.doc_id for c in delta.upserted] == ["a", "b"]
    assert delta.deleted == ("drop://y", "drop://z")


def test_plan_retirements_one_per_deletion() -> None:
    previous = snapshot_of([_cand("gone1", "1"), _cand("gone2", "2"), _cand("kept", "3")])
    delta = diff_snapshot(previous, [_cand("kept", "3")])
    retirements = plan_retirements(delta)
    assert [r.source_ref for r in retirements] == ["drop://gone1", "drop://gone2"]
    assert all(r.reason == "source manual removed" for r in retirements)


def test_no_deletions_plans_no_retirements() -> None:
    previous = snapshot_of([_cand("a", "1")])
    delta = diff_snapshot(previous, [_cand("a", "1")])
    assert plan_retirements(delta) == ()
