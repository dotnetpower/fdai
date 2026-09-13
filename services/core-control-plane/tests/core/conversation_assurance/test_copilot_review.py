from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fdai.core.conversation_assurance import (
    COPILOT_RUBRIC_NAMES,
    PrivateJsonlLedger,
    build_copilot_review_packet,
    import_copilot_review,
    write_copilot_review_packet,
)


def _packet() -> dict[str, object]:
    return build_copilot_review_packet(
        (
            {
                "case_id": "postgresql-list",
                "question": "List PostgreSQL servers.",
                "answer": "No matching servers were returned.",
                "evidence": {"request_id": "request-one", "verified": False},
            },
        ),
        created_at=datetime(2026, 9, 13, tzinfo=UTC).isoformat(),
    )


def _result(packet: dict[str, object]) -> dict[str, object]:
    case = packet["cases"][0]  # type: ignore[index]
    return {
        "schema_version": "1.0.0",
        "packet_digest": packet["packet_digest"],
        "reviewer_kind": "github_copilot_session",
        "reviewed_at": datetime(2026, 9, 13, 1, tzinfo=UTC).isoformat(),
        "reviews": [
            {
                "case_id": case["case_id"],  # type: ignore[index]
                "case_digest": case["case_digest"],  # type: ignore[index]
                "rubrics": [
                    {"name": name, "score": 0, "reason": "Expected value was absent."}
                    for name in COPILOT_RUBRIC_NAMES
                ],
            }
        ],
        "qualification_authority": False,
        "execution_authority": False,
    }


def test_packet_is_digest_bound_and_written_owner_only(tmp_path: Path) -> None:
    packet = _packet()
    destination = tmp_path / "packet.json"

    write_copilot_review_packet(destination, packet)

    assert json.loads(destination.read_text(encoding="utf-8")) == packet
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_packet_writer_refuses_existing_file_and_symlink(tmp_path: Path) -> None:
    packet = _packet()
    existing = tmp_path / "packet.json"
    existing.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_copilot_review_packet(existing, packet)

    target = tmp_path / "target.json"
    target.write_text("keep", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_copilot_review_packet(link, packet)


def test_import_rejects_packet_tampering_and_authority_claims(tmp_path: Path) -> None:
    packet = _packet()
    tampered = json.loads(json.dumps(packet))
    tampered["cases"][0]["answer"] = "Changed after export."

    with pytest.raises(ValueError, match="packet_digest"):
        import_copilot_review(
            packet=tampered,
            result=_result(packet),
            ledger=PrivateJsonlLedger(tmp_path / "reviews.jsonl"),
        )

    result = _result(packet)
    result["qualification_authority"] = True
    with pytest.raises(ValueError, match="qualification_authority"):
        import_copilot_review(
            packet=packet,
            result=result,
            ledger=PrivateJsonlLedger(tmp_path / "reviews.jsonl"),
        )


def test_import_computes_score_and_is_idempotent(tmp_path: Path) -> None:
    packet = _packet()
    result = _result(packet)
    ledger = PrivateJsonlLedger(tmp_path / "reviews.jsonl")

    first = import_copilot_review(packet=packet, result=result, ledger=ledger)
    second = import_copilot_review(packet=packet, result=result, ledger=ledger)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["reviewer_kind"] == "github_copilot_session"
    assert first["qualification_authority"] is False
    assert first["reviews"][0]["total_score"] == 0  # type: ignore[index]
    assert first["reviews"][0]["assurance_passed"] is False  # type: ignore[index]
    assert len(ledger.read()) == 1
    assert stat.S_IMODE(ledger.path.stat().st_mode) == 0o600


def test_import_rejects_noncanonical_rubric_order(tmp_path: Path) -> None:
    packet = _packet()
    result = _result(packet)
    result["reviews"][0]["rubrics"].reverse()  # type: ignore[index]

    with pytest.raises(ValueError, match="canonical order"):
        import_copilot_review(
            packet=packet,
            result=result,
            ledger=PrivateJsonlLedger(tmp_path / "reviews.jsonl"),
        )
