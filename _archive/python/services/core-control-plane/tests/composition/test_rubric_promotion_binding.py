from __future__ import annotations

from dataclasses import replace

import pytest
from fdai.composition import Container


class _ReceiptSource:
    def current(self, action_type_name: str):
        return None


class _ReceiptVerifier:
    def verify(self, receipt) -> bool:
        return False


def test_rubric_promotion_bindings_default_off(container: Container) -> None:
    assert container.rubric_promotion_receipt_source is None
    assert container.rubric_promotion_receipt_verifier is None


@pytest.mark.parametrize(
    "updates",
    [
        {"rubric_promotion_receipt_source": _ReceiptSource()},
        {"rubric_promotion_receipt_verifier": _ReceiptVerifier()},
    ],
)
def test_rubric_promotion_bindings_reject_half_wiring(
    container: Container,
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="source and verifier MUST be bound together"):
        replace(container, **updates)


def test_rubric_promotion_bindings_accept_complete_pair(container: Container) -> None:
    bound = replace(
        container,
        rubric_promotion_receipt_source=_ReceiptSource(),
        rubric_promotion_receipt_verifier=_ReceiptVerifier(),
    )

    assert bound.rubric_promotion_receipt_source is not None
    assert bound.rubric_promotion_receipt_verifier is not None
