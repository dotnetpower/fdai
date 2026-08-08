from fdai.core.conversation.attachment_directive import parse_attachment_directive
from fdai.shared.contracts import DocumentPurpose


def test_handover_requires_exact_leading_directive() -> None:
    directive = parse_attachment_directive("/handover transfer Thor ownership")

    assert directive.purpose is DocumentPurpose.HANDOVER_BOOTSTRAP
    assert directive.message == "transfer Thor ownership"
    assert directive.explicit is True


def test_plain_handover_prose_remains_knowledge_evidence() -> None:
    directive = parse_attachment_directive("Please explain this handover document")

    assert directive.purpose is DocumentPurpose.KNOWLEDGE_BASE
    assert directive.explicit is False


def test_prefix_collision_is_not_a_directive() -> None:
    directive = parse_attachment_directive("/handoverish text")

    assert directive.purpose is DocumentPurpose.KNOWLEDGE_BASE
    assert directive.explicit is False
