"""Var's source-aware exact-diff review remains distinct from action and ingestion approval."""

from collections.abc import Awaitable, Callable

from fdai.agents._framework.var_decisions import PendingHilTicket

ReviewAuthorizer = Callable[[str, str], bool | Awaitable[bool]]


class DocumentIntentReviewMixin:
    _approver_authorizer: ReviewAuthorizer | None
    _document_intent_approver_authorizer: ReviewAuthorizer | None = None

    def bind_document_intent_review_authorizer(self, authorizer: ReviewAuthorizer) -> None:
        if self._document_intent_approver_authorizer is not None:
            raise RuntimeError("document intent review authorizer is already bound")
        self._document_intent_approver_authorizer = authorizer

    def _document_intent_authorizer(
        self, ticket: PendingHilTicket
    ) -> tuple[ReviewAuthorizer | None, str]:
        if ticket.kind != "document_intent_projection":
            return self._approver_authorizer, ticket.action_type
        if self._document_intent_approver_authorizer is None:
            raise PermissionError("document intent review authorizer is unavailable")
        return self._document_intent_approver_authorizer, str(
            ticket.params.get("intent_digest", "")
        )
