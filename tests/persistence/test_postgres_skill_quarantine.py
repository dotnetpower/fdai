from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fdai.core.supply_chain.skill_quarantine import (
    QuarantinedSkillArtifact,
    QuarantinedSkillFile,
    SkillQuarantineState,
    SkillRevocation,
    SkillScanFinding,
    SkillScanSeverity,
    SkillScanVerdict,
    SkillUpdateCandidate,
    quarantine_artifact_digest,
)
from fdai.delivery.persistence.postgres_skill_quarantine import (
    _artifact_from_row,
    _artifact_values,
    _candidate_from_row,
    _candidate_values,
    _revocation_from_row,
    _revocation_values,
)

NOW = datetime(2026, 7, 20, 22, 0, tzinfo=UTC)


def _artifact() -> QuarantinedSkillArtifact:
    content = b"---\nname: example.skill\n---\nUse evidence.\n"
    files = (
        QuarantinedSkillFile(
            path="skills/example/SKILL.md",
            content_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
            media_type="text/markdown",
        ),
    )
    return QuarantinedSkillArtifact(
        quarantine_id="quarantine-example",
        source_id="operations-skills",
        source_revision="a" * 40,
        artifact_digest=quarantine_artifact_digest(files),
        files=files,
        publisher_signature=b"s" * 64,
        fetched_at=NOW,
        scanner_version="scanner-1",
        findings=(
            SkillScanFinding(
                scanner="deterministic-skill-scanner",
                code="reviewed",
                severity=SkillScanSeverity.INFO,
                path="skills/example/SKILL.md",
                detail="Artifact passed deterministic review.",
            ),
        ),
        verdict=SkillScanVerdict.PASS,
        state=SkillQuarantineState.PROPOSED,
    )


def test_quarantine_row_codec_round_trips_exact_bytes() -> None:
    columns = (
        "quarantine_id source_id source_revision artifact_digest files publisher_signature "
        "fetched_at scanner_version findings verdict state prior_installed_digest"
    ).split()
    artifact = _artifact()

    row = dict(zip(columns, _artifact_values(artifact), strict=True))

    assert _artifact_from_row(row) == artifact


def test_candidate_and_revocation_row_codecs_round_trip() -> None:
    candidate = SkillUpdateCandidate(
        candidate_id="skill-update-example",
        quarantine_id="quarantine-example",
        artifact_digest=_artifact().artifact_digest,
        prior_installed_digest=None,
        created_at=NOW,
    )
    candidate_columns = (
        "candidate_id quarantine_id artifact_digest prior_installed_digest created_at disabled"
    ).split()
    revocation = SkillRevocation(
        revocation_id="skill-revocation-example",
        source_id="operations-skills",
        artifact_digest=candidate.artifact_digest,
        reason="Publisher key was withdrawn.",
        revoked_at=NOW,
    )
    revocation_columns = "revocation_id source_id artifact_digest reason revoked_at".split()

    assert (
        _candidate_from_row(dict(zip(candidate_columns, _candidate_values(candidate), strict=True)))
        == candidate
    )
    assert (
        _revocation_from_row(
            dict(zip(revocation_columns, _revocation_values(revocation), strict=True))
        )
        == revocation
    )
