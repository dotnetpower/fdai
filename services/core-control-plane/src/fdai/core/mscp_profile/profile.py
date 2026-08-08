"""Versioned provenance for the FDAI MSCP operational profile."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationalProfile:
    """Identify the adopted safety profile without claiming MSCP conformance."""

    profile_id: str
    source_repository: str
    source_revision: str
    conformance_claimed: bool = False

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id MUST be non-empty")
        if not self.source_repository.strip():
            raise ValueError("source_repository MUST be non-empty")
        if len(self.source_revision) != 40 or any(
            character not in "0123456789abcdef" for character in self.source_revision
        ):
            raise ValueError("source_revision MUST be a lowercase 40-character git SHA")
        if self.conformance_claimed:
            raise ValueError("the FDAI operational profile MUST NOT claim full MSCP conformance")

    def audit_context(self) -> dict[str, object]:
        """Return stable, customer-agnostic provenance for an audit record."""

        return {
            "safety_profile": self.profile_id,
            "profile_source_ref": f"{self.source_repository}@{self.source_revision}",
            "conformance_claimed": self.conformance_claimed,
        }


DEFAULT_PROFILE = OperationalProfile(
    profile_id="mscp-operational-v1",
    source_repository="https://github.com/dotnetpower/mscp",
    source_revision="b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a",
)


__all__ = ["DEFAULT_PROFILE", "OperationalProfile"]
