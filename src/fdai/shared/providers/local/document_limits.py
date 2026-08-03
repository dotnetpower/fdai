"""Immutable resource ceilings for local document parsing."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentParserPolicy:
    max_input_bytes: int = 32 * 1024 * 1024
    max_units: int = 20_000
    max_text_characters: int = 5_000_000
    max_markdown_tokens: int = 100_000
    max_markdown_nesting: int = 64
    max_sgml_nesting: int = 64
    max_ooxml_members: int = 2_048
    max_ooxml_expanded_bytes: int = 64 * 1024 * 1024
    max_ooxml_compression_ratio: float = 100.0
    max_ooxml_xml_member_bytes: int = 16 * 1024 * 1024
    max_ooxml_xml_depth: int = 128
    max_pdf_pages: int = 1_000
    max_pdf_objects: int = 10_000
    max_pdf_raw_stream_bytes: int = 32 * 1024 * 1024
    max_pdf_decoded_stream_bytes: int = 64 * 1024 * 1024
    max_pdf_units: int = 20_000
    max_pdf_characters: int = 2_000_000
    max_ocr_pages: int = 1_000
    max_ocr_units: int = 20_000
    max_ocr_characters: int = 2_000_000

    def __post_init__(self) -> None:
        integer_limits = (
            self.max_input_bytes,
            self.max_units,
            self.max_text_characters,
            self.max_markdown_tokens,
            self.max_markdown_nesting,
            self.max_sgml_nesting,
            self.max_ooxml_members,
            self.max_ooxml_expanded_bytes,
            self.max_ooxml_xml_member_bytes,
            self.max_ooxml_xml_depth,
            self.max_pdf_pages,
            self.max_pdf_objects,
            self.max_pdf_raw_stream_bytes,
            self.max_pdf_decoded_stream_bytes,
            self.max_pdf_units,
            self.max_pdf_characters,
            self.max_ocr_pages,
            self.max_ocr_units,
            self.max_ocr_characters,
        )
        if any(type(value) is not int or value < 1 for value in integer_limits):
            raise ValueError("document parser integer limits MUST be positive")
        if (
            not math.isfinite(self.max_ooxml_compression_ratio)
            or self.max_ooxml_compression_ratio < 1.0
        ):
            raise ValueError("document parser compression ratio MUST be finite and at least one")


DEFAULT_DOCUMENT_PARSER_POLICY = DocumentParserPolicy()


__all__ = ["DEFAULT_DOCUMENT_PARSER_POLICY", "DocumentParserPolicy"]
