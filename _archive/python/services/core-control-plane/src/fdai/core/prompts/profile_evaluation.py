"""Deterministic active-versus-shadow prompt profile comparison."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.core.prompts.profiles import PromptProfileMode, compose_static_selection
from fdai.core.prompts.registry import PromptRegistry


@dataclass(frozen=True, slots=True)
class PromptProfileComparison:
    """Content-free profile size and identity evidence."""

    capability_id: str
    active_profile_id: str
    active_profile_digest: str
    treatment_profile_id: str
    treatment_profile_digest: str
    active_tokens: int
    treatment_tokens: int

    @property
    def token_reduction_rate(self) -> float:
        """Return the deterministic static-token reduction."""

        return (self.active_tokens - self.treatment_tokens) / self.active_tokens


def compare_prompt_profiles(
    registry: PromptRegistry,
    *,
    capability_id: str,
    treatment_profile_id: str,
) -> PromptProfileComparison:
    """Compare one explicit shadow treatment with the active profile."""

    active = registry.resolve(capability_id)
    treatment = registry.resolve(capability_id, profile_id=treatment_profile_id)
    if active.profile is None or active.profile.mode is not PromptProfileMode.ACTIVE:
        raise ValueError("prompt profile comparison requires one exact active profile")
    if treatment.profile is None or treatment.profile.mode is not PromptProfileMode.SHADOW:
        raise ValueError("prompt profile treatment MUST be an exact shadow profile")
    active_prompt = compose_static_selection(active)
    treatment_prompt = compose_static_selection(treatment)
    if active_prompt.profile_digest is None or treatment_prompt.profile_digest is None:
        raise ValueError("prompt profile comparison requires content-bound profile digests")
    return PromptProfileComparison(
        capability_id=capability_id,
        active_profile_id=active.profile.id,
        active_profile_digest=active_prompt.profile_digest,
        treatment_profile_id=treatment.profile.id,
        treatment_profile_digest=treatment_prompt.profile_digest,
        active_tokens=active_prompt.token_estimate,
        treatment_tokens=treatment_prompt.token_estimate,
    )


__all__ = ["PromptProfileComparison", "compare_prompt_profiles"]
