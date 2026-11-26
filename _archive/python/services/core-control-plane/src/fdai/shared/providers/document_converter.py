"""CSP-neutral contract for isolated binary document conversion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Protocol, runtime_checkable

_CONVERTER_ID = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_SUFFIX = re.compile(r"^\.[a-z0-9]{1,15}$")


@dataclass(frozen=True, slots=True)
class DocumentConversionRequest:
    """One bounded, content-only conversion request."""

    converter_id: str
    source_ref: str
    source_suffix: str
    content: bytes = field(repr=False)
    max_output_bytes: int = 5_000_000

    def __post_init__(self) -> None:
        if _CONVERTER_ID.fullmatch(self.converter_id) is None:
            raise ValueError("document converter_id MUST be lowercase ASCII")
        source_path = PurePosixPath(self.source_ref)
        if (
            not self.source_ref
            or len(self.source_ref) > 2_048
            or source_path.is_absolute()
            or ".." in source_path.parts
        ):
            raise ValueError("document source_ref MUST be a bounded relative path")
        if _SUFFIX.fullmatch(self.source_suffix) is None:
            raise ValueError("document source_suffix MUST be a lowercase file suffix")
        if not self.content:
            raise ValueError("document conversion content MUST be non-empty")
        if not 1 <= self.max_output_bytes <= 50_000_000:
            raise ValueError("document max_output_bytes MUST be in [1, 50000000]")


@dataclass(frozen=True, slots=True)
class DocumentConversionResult:
    """UTF-8 text returned by an isolated converter."""

    text: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("document conversion result MUST contain text")


@runtime_checkable
class DocumentConverter(Protocol):
    """Convert one bounded binary document without exposing host paths."""

    async def convert(
        self,
        request: DocumentConversionRequest,
    ) -> DocumentConversionResult: ...


__all__ = [
    "DocumentConversionRequest",
    "DocumentConversionResult",
    "DocumentConverter",
]
