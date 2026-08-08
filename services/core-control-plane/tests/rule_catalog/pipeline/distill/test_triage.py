"""Tests for deterministic manual triage (filter, dedupe, authority, priority)."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.rule_catalog.pipeline.distill.triage import (
    TriagePolicy,
    authority_score,
    dedupe_exact,
    prioritize,
    triage_filter,
)
from fdai.shared.providers.manual_source import ManualCandidate

_NOW = datetime(2026, 7, 13, tzinfo=UTC)


def _cand(doc_id: str, **over: object) -> ManualCandidate:
    base: dict[str, object] = {"doc_id": doc_id, "source_ref": f"drop://{doc_id}"}
    base.update(over)
    return ManualCandidate(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# triage_filter
# ---------------------------------------------------------------------------


def test_empty_policy_keeps_everything() -> None:
    cands = [_cand("a"), _cand("b")]
    result = triage_filter(cands, TriagePolicy(), now=_NOW)
    assert len(result.kept) == 2
    assert result.dropped == ()


def test_required_label_drops_unlabelled() -> None:
    policy = TriagePolicy(required_labels=frozenset({"runbook"}))
    kept_cand = _cand("a", labels=("runbook", "ops"))
    dropped_cand = _cand("b", labels=("meeting",))
    result = triage_filter([kept_cand, dropped_cand], policy, now=_NOW)
    assert [c.doc_id for c in result.kept] == ["a"]
    assert result.dropped[0].reason == "missing required label"


def test_excluded_label_drops() -> None:
    policy = TriagePolicy(excluded_labels=frozenset({"draft"}))
    result = triage_filter([_cand("a", labels=("draft",))], policy, now=_NOW)
    assert result.kept == ()
    assert result.dropped[0].reason == "carries excluded label"


def test_require_verified_and_space_and_views() -> None:
    policy = TriagePolicy(
        require_verified=True,
        required_spaces=frozenset({"ops"}),
        min_view_count=10,
    )
    good = _cand("a", verified=True, space="ops", view_count=20)
    unverified = _cand("b", verified=False, space="ops", view_count=20)
    wrong_space = _cand("c", verified=True, space="hr", view_count=20)
    few_views = _cand("d", verified=True, space="ops", view_count=1)
    result = triage_filter([good, unverified, wrong_space, few_views], policy, now=_NOW)
    assert [c.doc_id for c in result.kept] == ["a"]
    reasons = {d.candidate.doc_id: d.reason for d in result.dropped}
    assert reasons == {
        "b": "not verified",
        "c": "outside required space",
        "d": "below min view count",
    }


def test_stale_drop_but_missing_timestamp_kept() -> None:
    policy = TriagePolicy(max_stale_days=30)
    stale = _cand("old", last_edited="2026-01-01T00:00:00Z")
    fresh = _cand("new", last_edited="2026-07-10T00:00:00Z")
    no_ts = _cand("unknown", last_edited="")
    result = triage_filter([stale, fresh, no_ts], policy, now=_NOW)
    kept = {c.doc_id for c in result.kept}
    assert kept == {"new", "unknown"}  # missing timestamp is not penalised
    assert result.dropped[0].candidate.doc_id == "old"
    assert result.dropped[0].reason == "stale"


def test_stale_uses_full_precision_not_day_truncation() -> None:
    from datetime import timedelta

    policy = TriagePolicy(max_stale_days=30)
    # 30.5 days old must be stale (day-truncation would wrongly keep it at .days==30).
    edited_305 = (_NOW - timedelta(days=30, hours=12)).isoformat()
    result = triage_filter([_cand("d305", last_edited=edited_305)], policy, now=_NOW)
    assert result.dropped and result.dropped[0].reason == "stale"

    # 29.5 days old stays fresh.
    edited_295 = (_NOW - timedelta(days=29, hours=12)).isoformat()
    result2 = triage_filter([_cand("d295", last_edited=edited_295)], policy, now=_NOW)
    assert [c.doc_id for c in result2.kept] == ["d295"]


# ---------------------------------------------------------------------------
# authority_score + dedupe_exact
# ---------------------------------------------------------------------------


def test_authority_score_orders_by_signals() -> None:
    hub = _cand("hub", inbound_links=10, verified=True, view_count=500)
    leaf = _cand("leaf", inbound_links=0, verified=False, view_count=1)
    assert authority_score(hub) > authority_score(leaf)


def test_dedupe_keeps_highest_authority_survivor() -> None:
    a = _cand("a", content_sha="sha1", inbound_links=1)
    b = _cand("b", content_sha="sha1", inbound_links=9)  # same bytes, more authority
    c = _cand("c", content_sha="sha2")
    unique, dropped = dedupe_exact([a, b, c])
    unique_ids = {x.doc_id for x in unique}
    assert unique_ids == {"b", "c"}
    assert dropped[0].candidate.doc_id == "a"
    assert dropped[0].reason == "exact duplicate"


def test_dedupe_never_collapses_empty_sha() -> None:
    a = _cand("a", content_sha="")
    b = _cand("b", content_sha="")
    unique, dropped = dedupe_exact([a, b])
    assert {x.doc_id for x in unique} == {"a", "b"}
    assert dropped == ()


# ---------------------------------------------------------------------------
# prioritize
# ---------------------------------------------------------------------------


def test_incident_referenced_sorts_first() -> None:
    plain = _cand("plain", inbound_links=100)  # high authority but no incident
    referenced = _cand("ref", inbound_links=0)
    ordered = prioritize([plain, referenced], incident_refs=frozenset({"drop://ref"}))
    assert ordered[0].doc_id == "ref"  # incident beats raw authority


def test_prioritize_is_deterministic() -> None:
    cands = [_cand("a", view_count=5), _cand("b", view_count=5), _cand("c", view_count=9)]
    first = prioritize(cands)
    second = prioritize(list(reversed(cands)))
    assert [c.doc_id for c in first] == [c.doc_id for c in second]
    assert first[0].doc_id == "c"  # highest view_count leads


# ---------------------------------------------------------------------------
# timestamp parsing edge cases
# ---------------------------------------------------------------------------


def test_malformed_timestamp_is_not_stale() -> None:
    policy = TriagePolicy(max_stale_days=1)
    bad = _cand("bad", last_edited="not-a-date")
    result = triage_filter([bad], policy, now=_NOW)
    assert [c.doc_id for c in result.kept] == ["bad"]  # unparsable = best-effort keep


def test_naive_timestamp_is_treated_as_utc() -> None:
    policy = TriagePolicy(max_stale_days=30)
    # last_edited without a timezone offset must still evaluate as UTC.
    stale_naive = _cand("naive", last_edited="2026-01-01T00:00:00")
    result = triage_filter([stale_naive], policy, now=_NOW)
    assert result.kept == ()
    assert result.dropped[0].reason == "stale"


def test_naive_now_is_accepted() -> None:
    policy = TriagePolicy(max_stale_days=30)
    naive_now = datetime(2026, 7, 13)  # noqa: DTZ001 - exercising the naive-now guard
    stale = _cand("old", last_edited="2026-01-01T00:00:00Z")
    result = triage_filter([stale], policy, now=naive_now)
    assert result.dropped[0].reason == "stale"


def test_prioritize_handles_malformed_last_edited() -> None:
    a = _cand("a", last_edited="garbage")
    b = _cand("b", last_edited="2026-07-10T00:00:00Z")
    ordered = prioritize([a, b])
    assert {c.doc_id for c in ordered} == {"a", "b"}  # no crash on bad date
