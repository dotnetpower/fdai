import pytest
from fdai.agents._framework.var_decisions import PendingHilTicket
from fdai.agents._framework.var_document_intent import (
    DocumentIntentReviewMixin,
    ReviewAuthorizer,
)

INTENT_DIGEST = "sha256:" + "1" * 64


def _allow(principal: str, subject: str) -> bool:
    return principal == "human:reviewer" and subject == INTENT_DIGEST


def _deny(principal: str, subject: str) -> bool:
    return False


def _ticket(kind: str = "document_intent_projection") -> PendingHilTicket:
    return PendingHilTicket(
        correlation_id="intent-review-test",
        action_type="example_action",
        resource_id=None,
        quorum_required=1,
        kind=kind,
        params={"intent_digest": INTENT_DIGEST},
    )


def test_document_review_never_borrows_the_action_authorizer() -> None:
    review = DocumentIntentReviewMixin()
    review._approver_authorizer = _allow

    with pytest.raises(PermissionError, match="review authorizer is unavailable"):
        review._document_intent_authorizer(_ticket())


def test_document_review_binding_is_single_assignment() -> None:
    review = DocumentIntentReviewMixin()
    review.bind_document_intent_review_authorizer(_allow)

    with pytest.raises(RuntimeError, match="already bound"):
        review.bind_document_intent_review_authorizer(_deny)

    authorizer, subject = review._document_intent_authorizer(_ticket())
    assert authorizer is _allow
    assert subject == INTENT_DIGEST
    assert authorizer("human:reviewer", subject)
    assert not authorizer("human:other", subject)


@pytest.mark.parametrize(
    "ordinary",
    [pytest.param(None, id="unavailable"), pytest.param(_deny, id="configured")],
)
def test_document_binding_preserves_the_existing_action_authorizer(
    ordinary: ReviewAuthorizer | None,
) -> None:
    review = DocumentIntentReviewMixin()
    review._approver_authorizer = ordinary
    review.bind_document_intent_review_authorizer(_allow)

    authorizer, subject = review._document_intent_authorizer(_ticket("action"))

    assert authorizer is ordinary
    assert subject == "example_action"


def test_document_binding_is_not_shared_between_reviewers() -> None:
    configured = DocumentIntentReviewMixin()
    configured.bind_document_intent_review_authorizer(_allow)
    unbound = DocumentIntentReviewMixin()
    unbound._approver_authorizer = _allow

    with pytest.raises(PermissionError, match="review authorizer is unavailable"):
        unbound._document_intent_authorizer(_ticket())
