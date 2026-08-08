"""Explicit channel-attachment purpose directives.

Attachment purpose is operator intent, never inferred from file contents. The
parser accepts only an exact leading directive so ordinary prose mentioning a
handover cannot accidentally open a governance pull request.
"""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.contracts import DocumentPurpose

_HANDOVER_PREFIXES = ("/handover", "/attach handover", "인수인계 문서:")
_KNOWLEDGE_PREFIXES = ("/knowledge", "/attach knowledge", "참고 문서:")


@dataclass(frozen=True, slots=True)
class AttachmentDirective:
    purpose: DocumentPurpose
    message: str
    explicit: bool


def parse_attachment_directive(text: str) -> AttachmentDirective:
    """Resolve an exact leading attachment directive.

    Unmarked attachments remain knowledge-base evidence. A handover is never
    inferred from filenames, MIME types, document text, or a mid-sentence word.
    """
    stripped = text.strip()
    for prefix in _HANDOVER_PREFIXES:
        remainder = _strip_prefix(stripped, prefix)
        if remainder is not None:
            return AttachmentDirective(
                purpose=DocumentPurpose.HANDOVER_BOOTSTRAP,
                message=remainder,
                explicit=True,
            )
    for prefix in _KNOWLEDGE_PREFIXES:
        remainder = _strip_prefix(stripped, prefix)
        if remainder is not None:
            return AttachmentDirective(
                purpose=DocumentPurpose.KNOWLEDGE_BASE,
                message=remainder,
                explicit=True,
            )
    return AttachmentDirective(
        purpose=DocumentPurpose.KNOWLEDGE_BASE,
        message=stripped,
        explicit=False,
    )


def _strip_prefix(text: str, prefix: str) -> str | None:
    if not text.casefold().startswith(prefix.casefold()):
        return None
    if len(text) > len(prefix) and not (prefix.endswith(":") or text[len(prefix)].isspace()):
        return None
    return text[len(prefix) :].strip()


__all__ = ["AttachmentDirective", "parse_attachment_directive"]
