"""Stewardship draft delivery stays idempotent and review-only."""

from __future__ import annotations

from uuid import UUID

import pytest
from fdai.core.stewardship.governance import (
    STEWARDSHIP_LABELS,
    STEWARDSHIP_PATCH_PATH,
    StewardshipGovernanceError,
    StewardshipGovernanceService,
    stewardship_idempotency_key,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.remediation_pr import PublishReceipt, RemediationPr
from fdai_service_contracts.handover import (
    HandoverDraftArtifact,
    HandoverDraftOutcome,
    HandoverMapping,
    HandoverPerson,
    HandoverSourceSpan,
    StewardResponsibility,
    StewardshipDraft,
)

UPLOAD_ID = UUID("11111111-1111-4111-8111-111111111111")
DOCUMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
VERSION_ID = UUID("33333333-3333-4333-8333-333333333333")
YAML = "version: 1\nagents:\n  - agent_name: Freyr\n"


class _Publisher:
    """Idempotent-by-key fake mirroring the adapter contract."""

    def __init__(self, *, fail_first: bool = False) -> None:
        self.published: list[RemediationPr] = []
        self._by_key: dict[str, str] = {}
        self._fail_first = fail_first

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        self.published.append(pr)
        if self._fail_first:
            self._fail_first = False
            self._by_key[pr.idempotency_key] = f"repo#{len(self._by_key) + 1}"
            raise TimeoutError("ambiguous transport failure")
        existing = self._by_key.get(pr.idempotency_key)
        if existing is not None:
            return PublishReceipt(pr_ref=existing, already_existed=True)
        pr_ref = f"repo#{len(self._by_key) + 1}"
        self._by_key[pr.idempotency_key] = pr_ref
        return PublishReceipt(pr_ref=pr_ref)


def _mapping(agent: str = "Freyr") -> HandoverMapping:
    return HandoverMapping(
        agent_name=agent,
        person=HandoverPerson(display_name="Steward Example", oid="oid-example"),
        responsibility=StewardResponsibility.ACCOUNTABLE,
        confidence=0.9,
        citations=(HandoverSourceSpan(doc_id="doc-1", line=4, quote="Freyr steward"),),
    )


def _artifact(
    *,
    outcome: HandoverDraftOutcome = HandoverDraftOutcome.DRAFTED,
    mappings: tuple[HandoverMapping, ...] | None = None,
    yaml: str = YAML,
    warnings: tuple[str, ...] = ("one unresolved reviewer",),
) -> HandoverDraftArtifact:
    return HandoverDraftArtifact(
        upload_id=UPLOAD_ID,
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        draft=StewardshipDraft(
            outcome=outcome,
            mappings=mappings if mappings is not None else (_mapping(),),
            warnings=warnings,
        ),
        yaml=yaml,
    )


async def test_draft_publishes_one_review_only_pr() -> None:
    publisher = _Publisher()

    result = await StewardshipGovernanceService(publisher=publisher).publish(_artifact())

    assert result.published is True
    assert result.receipt is not None
    assert result.receipt.already_existed is False
    (published,) = publisher.published
    assert published.patch_path == STEWARDSHIP_PATCH_PATH
    assert published.patch == YAML
    assert published.labels == STEWARDSHIP_LABELS
    assert published.mode is Mode.SHADOW
    assert "changes no active ownership" in published.body


async def test_retry_reuses_one_draft_pr() -> None:
    publisher = _Publisher()
    service = StewardshipGovernanceService(publisher=publisher)
    artifact = _artifact()

    first = await service.publish(artifact)
    second = await service.publish(artifact)

    assert first.idempotency_key == second.idempotency_key
    assert second.receipt is not None
    assert second.receipt.already_existed is True
    assert first.receipt is not None
    assert second.receipt.pr_ref == first.receipt.pr_ref


async def test_retry_after_ambiguous_failure_reuses_the_same_key() -> None:
    publisher = _Publisher(fail_first=True)
    service = StewardshipGovernanceService(publisher=publisher)
    artifact = _artifact()

    with pytest.raises(TimeoutError):
        await service.publish(artifact)
    retried = await service.publish(artifact)

    assert retried.receipt is not None
    assert retried.receipt.already_existed is True
    assert {pr.idempotency_key for pr in publisher.published} == {retried.idempotency_key}


async def test_changed_yaml_produces_a_new_key() -> None:
    publisher = _Publisher()
    service = StewardshipGovernanceService(publisher=publisher)

    first = await service.publish(_artifact())
    second = await service.publish(_artifact(yaml=f"{YAML}  - agent_name: Njord\n"))

    assert first.idempotency_key != second.idempotency_key
    assert second.receipt is not None
    assert second.receipt.already_existed is False


async def test_abstained_and_empty_drafts_are_never_published() -> None:
    publisher = _Publisher()
    service = StewardshipGovernanceService(publisher=publisher)

    abstained = await service.publish(_artifact(outcome=HandoverDraftOutcome.ABSTAINED))
    empty = await service.publish(_artifact(mappings=()))

    assert (abstained.published, abstained.reason) == (False, "abstained_draft")
    assert (empty.published, empty.reason) == (False, "no_mapping")
    assert publisher.published == []


async def test_blank_or_oversized_yaml_fails_closed() -> None:
    service = StewardshipGovernanceService(publisher=_Publisher())

    with pytest.raises(StewardshipGovernanceError, match="non-empty"):
        await service.publish(_artifact(yaml="   "))
    with pytest.raises(StewardshipGovernanceError, match="bounded size"):
        await service.publish(_artifact(yaml="a" * (256 * 1024 + 1)))


def test_idempotency_key_is_stable_and_content_addressed() -> None:
    first = stewardship_idempotency_key(_artifact())
    second = stewardship_idempotency_key(_artifact())

    assert first == second
    assert first.startswith("stewardship-handover:")
    assert stewardship_idempotency_key(_artifact(yaml=f"{YAML}# note\n")) != first


async def test_metadata_carries_no_person_or_secret_value() -> None:
    publisher = _Publisher()

    await StewardshipGovernanceService(publisher=publisher).publish(_artifact())

    (published,) = publisher.published
    assert set(published.metadata) == {
        "upload_id",
        "document_id",
        "version_id",
        "schema_version",
    }
    assert "oid-example" not in str(published.metadata)
    assert "Steward Example" not in published.body


async def test_pr_body_truncates_an_unbounded_warning_list() -> None:
    publisher = _Publisher()
    artifact = _artifact(warnings=tuple(f"warning-{index}" for index in range(50)))

    result = await StewardshipGovernanceService(publisher=publisher).publish(artifact)

    assert result.published is True
    body = publisher.published[0].body
    assert body.count("- warning-") == 20
    assert "30 more warning(s) truncated" in body
