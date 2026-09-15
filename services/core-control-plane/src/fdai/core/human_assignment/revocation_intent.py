"""Immutable references for an independently reviewed assignment revocation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True, slots=True)
class AssignmentRevocation:
    """Pin the old grant and replacements; these references grant no removal authority."""

    case_id: str
    revision: int
    replacement_revisions: Mapping[str, int]

    def __post_init__(self) -> None:
        _case_id(self.case_id)
        _revision(self.revision)
        if not isinstance(self.replacement_revisions, Mapping):
            raise ValueError("revocation replacements MUST be an object")
        if not 1 <= len(self.replacement_revisions) <= 30:
            raise ValueError("revocation requires between 1 and 30 replacement cases")
        for case_id, revision in self.replacement_revisions.items():
            _case_id(case_id)
            _revision(revision)
            if case_id == self.case_id:
                raise ValueError("revocation target cannot be its own replacement")
        object.__setattr__(
            self,
            "replacement_revisions",
            MappingProxyType(dict(sorted(self.replacement_revisions.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return stable serializable references without changing their reviewed revision."""
        return {
            "case_id": self.case_id,
            "revision": self.revision,
            "replacement_revisions": dict(self.replacement_revisions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AssignmentRevocation:
        """Reject unknown, missing, coerced, or unbounded fields at stored/wire ingress."""
        if set(value) != {"case_id", "revision", "replacement_revisions"}:
            raise ValueError("revocation fields are invalid")
        return cls(value["case_id"], value["revision"], value["replacement_revisions"])


def _case_id(value: object) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or value != value.strip():
        raise ValueError("revocation case reference MUST be bounded exact text")


def _revision(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("revocation revision MUST be a positive integer")


__all__ = ["AssignmentRevocation"]
