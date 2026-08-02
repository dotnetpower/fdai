"""Text normalization and integrity checks for chat verification."""

from __future__ import annotations

import unicodedata


def answers_match(provisional: str, canonical: str) -> bool:
    provisional_nfc = unicodedata.normalize("NFC", provisional.strip())
    canonical_nfc = unicodedata.normalize("NFC", canonical.strip())
    return provisional_nfc == canonical_nfc


def answer_text_is_well_formed(value: str) -> bool:
    for character in value:
        codepoint = ord(character)
        if character == "\ufffd" or 0xD800 <= codepoint <= 0xDFFF:
            return False
        if (codepoint < 0x20 and character not in "\t\n\r") or 0x7F <= codepoint <= 0x9F:
            return False
        if 0x202A <= codepoint <= 0x202E or 0x2066 <= codepoint <= 0x2069:
            return False
    return True
