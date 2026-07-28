"""Reusable validation primitives for public evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from unicodedata import category

from pydantic import AfterValidator, StringConstraints


def _without_controls(value: str) -> str:
    if any(category(character) in {"Cc", "Cf"} for character in value):
        raise ValueError("text MUST NOT contain control or format characters")
    return value


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp MUST include a timezone")
    return value


Identifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]
BoundedText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=20_000, strip_whitespace=True),
    AfterValidator(_without_controls),
]
MediaType = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=127,
        to_lower=True,
        pattern=r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$",
    ),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
AwareDatetime = Annotated[datetime, AfterValidator(_aware_datetime)]

__all__ = [
    "AwareDatetime",
    "BoundedText",
    "Identifier",
    "MediaType",
    "Sha256Digest",
]
