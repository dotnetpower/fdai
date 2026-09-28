"""Validation-only lexing of model-authored answer text for V-CLAIM.

These helpers never infer meaning. They find the tokens in the model's own prose
that could carry an operational literal, such as an identity, a number, or a
numeral, so V-CLAIM can require each one to be bound to verified evidence.
"""

from __future__ import annotations

import unicodedata

IDENTITY_JOINERS = frozenset("-_./:")
NUMBER_QUALIFIERS = frozenset("+-<>~\u2248\u2264\u2265\u00b1")
_ALLOWED_CONTROLS = frozenset("\n\t")


def text_violations(text: str) -> list[str]:
    """Reject control or format characters and compatibility forms of ASCII letters or digits.

    A full-width or styled letter or digit could display as an identity or number
    that no ASCII token check sees, while typographic forms such as an ellipsis or a
    no-break space normalize to punctuation or space and stay allowed.
    """

    violations: list[str] = []
    if any(
        unicodedata.category(character) in {"Cc", "Cf"} and character not in _ALLOWED_CONTROLS
        for character in text
    ):
        violations.append("control_character")
    if any(_disguises_ascii(character) for character in text):
        violations.append("text_not_normalized")
    return violations


def tokens(text: str) -> list[tuple[int, str]]:
    """Split text into ASCII identity tokens and non-ASCII word tokens.

    ASCII letters and digits join through internal ``-_./:`` characters; a
    boundary between ASCII and non-ASCII characters always splits, so a Korean
    particle never hides the name or number it follows.
    """

    found: list[tuple[int, str]] = []
    start: int | None = None
    kind: str | None = None
    for index, character in enumerate(text):
        current = _class(text, index, character, kind)
        if current != kind:
            if kind is not None and start is not None:
                found.append((start, text[start:index]))
            start, kind = (index, current) if current is not None else (None, None)
    if kind is not None and start is not None:
        found.append((start, text[start:]))
    return found


def literal_shaped(token: str, identities: set[str]) -> bool:
    """Return whether a token could state an identity, a number, or a numeral.

    Every joined ASCII token counts, because an invented name such as ``payments-db``
    has the same shape as prose such as ``read-only``. A false rejection costs one
    regeneration with the typed reason; a false acceptance would show an unverified
    identity, so the check stays conservative.
    """

    if token in identities or any(character.isnumeric() for character in token):
        return True
    return token.isascii() and any(character in IDENTITY_JOINERS for character in token)


def code_parts(code: str) -> frozenset[str]:
    """Return the exact segments of one Core-issued limitation code, split at ``:``."""

    return frozenset(token for segment in code.split(":") for _start, token in tokens(segment))


def _disguises_ascii(character: str) -> bool:
    if character.isascii():
        return False
    normalized = unicodedata.normalize("NFKC", character)
    return normalized != character and any(item.isascii() and item.isalnum() for item in normalized)


def _class(text: str, index: int, character: str, kind: str | None) -> str | None:
    if character.isascii() and character.isalnum():
        return "ascii"
    if not character.isascii() and (character.isalnum() or character.isnumeric()):
        return "word"
    following = text[index + 1] if index + 1 < len(text) else ""
    if (
        character in IDENTITY_JOINERS
        and kind == "ascii"
        and following.isascii()
        and following.isalnum()
    ):
        return "ascii"
    return None


__all__ = [
    "IDENTITY_JOINERS",
    "NUMBER_QUALIFIERS",
    "code_parts",
    "literal_shaped",
    "text_violations",
    "tokens",
]
