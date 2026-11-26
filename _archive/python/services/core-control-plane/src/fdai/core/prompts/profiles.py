"""Exact prompt-profile contracts and fail-closed selection budgets."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.prompts.budget import estimate_prompt_tokens
from fdai.core.prompts.types import (
    ComposedPrompt,
    LayerRef,
    PromptArtifact,
    PromptAssemblyMode,
    PromptAssemblyReceipt,
    PromptLayer,
    PromptProfileEvidence,
    validate_assembly_keys,
)

_COMPONENT_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,127}$")
_MAX_CAPABILITY_CHARS = 128


class PromptProfileMode(StrEnum):
    """Lifecycle state for one exact prompt composition."""

    ACTIVE = "active"
    SHADOW = "shadow"


@dataclass(frozen=True, slots=True)
class PromptArtifactRef:
    """Exact immutable artifact selected by a prompt profile."""

    id: str
    version: int
    layer: PromptLayer
    when_any: tuple[str, ...] = ()
    covers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _COMPONENT_ID.fullmatch(self.id) is None:
            raise ValueError("prompt artifact ref id MUST be a bounded canonical id")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("prompt artifact ref version MUST be a positive integer")
        if not isinstance(self.layer, PromptLayer):
            raise ValueError("prompt artifact ref layer MUST be a PromptLayer")
        validate_assembly_keys(self.when_any, name="when_any")
        validate_assembly_keys(self.covers, name="covers")
        if self.covers and not self.when_any:
            raise ValueError("prompt artifact ref covers requires when_any")

    @property
    def conditional(self) -> bool:
        """True when this pack joins a composition only for matching assembly keys."""

        return bool(self.when_any)

    def digest_payload(self) -> dict[str, object]:
        """Return digest fields; unconditional refs keep their historical shape."""

        payload: dict[str, object] = {
            "id": self.id,
            "layer": self.layer.value,
            "version": self.version,
        }
        if self.when_any:
            payload["when_any"] = sorted(self.when_any)
            payload["covers"] = sorted(self.covers)
        return payload


@dataclass(frozen=True, slots=True)
class PromptProfile:
    """One exact root-and-pack composition with bounded model input."""

    id: str
    version: int
    capability_id: str
    mode: PromptProfileMode
    root: PromptArtifactRef
    packs: tuple[PromptArtifactRef, ...]
    system_token_budget: int
    request_token_budget: int
    reserved_output_tokens: int
    promotion_evidence: tuple[str, ...]
    provenance_source: str
    model_role: str | None = None
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        if _COMPONENT_ID.fullmatch(self.id) is None:
            raise ValueError("prompt profile id MUST be a bounded canonical id")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("prompt profile version MUST be a positive integer")
        if (
            not isinstance(self.capability_id, str)
            or not self.capability_id
            or len(self.capability_id) > _MAX_CAPABILITY_CHARS
        ):
            raise ValueError("prompt profile capability_id MUST be non-empty and bounded")
        if not isinstance(self.mode, PromptProfileMode):
            raise ValueError("prompt profile mode MUST be a PromptProfileMode")
        for name, value in (
            ("system_token_budget", self.system_token_budget),
            ("request_token_budget", self.request_token_budget),
            ("reserved_output_tokens", self.reserved_output_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"prompt profile {name} MUST be a positive integer")
        if self.request_token_budget <= self.system_token_budget:
            raise ValueError("prompt profile request budget MUST exceed its system budget")
        if self.reserved_output_tokens >= self.request_token_budget:
            raise ValueError("prompt profile reserved output MUST be below its request budget")
        if len({(ref.id, ref.version, ref.layer) for ref in self.packs}) != len(self.packs):
            raise ValueError("prompt profile pack refs MUST be unique")
        if self.root.conditional or self.root.covers:
            raise ValueError("prompt profile root MUST NOT be conditional")
        if any(not item for item in self.promotion_evidence):
            raise ValueError("prompt profile promotion evidence MUST be non-empty")
        if len(set(self.promotion_evidence)) != len(self.promotion_evidence):
            raise ValueError("prompt profile promotion evidence MUST be unique")
        if not self.provenance_source:
            raise ValueError("prompt profile provenance source MUST be non-empty")
        if self.model_role is not None and (
            not isinstance(self.model_role, str)
            or not self.model_role
            or len(self.model_role) > _MAX_CAPABILITY_CHARS
        ):
            raise ValueError("prompt profile model_role MUST be bounded when provided")
        if self.reasoning_effort is not None and self.reasoning_effort not in {
            "minimal",
            "low",
            "medium",
            "high",
        }:
            raise ValueError("prompt profile reasoning_effort MUST be reviewed when provided")

    @property
    def dynamic(self) -> bool:
        """True when at least one pack is selected per call by assembly keys."""

        return any(ref.conditional for ref in self.packs)

    @property
    def governed_keys(self) -> tuple[str, ...]:
        """Result keys whose guidance lives only in conditional packs."""

        return tuple(sorted({key for ref in self.packs for key in ref.covers}))

    @property
    def digest(self) -> str:
        """Return a content digest for selection replay and rollback."""

        payload = {
            "capability_id": self.capability_id,
            "id": self.id,
            "mode": self.mode.value,
            "packs": [ref.digest_payload() for ref in self.packs],
            "promotion_evidence": list(self.promotion_evidence),
            "provenance_source": self.provenance_source,
            "request_token_budget": self.request_token_budget,
            "reserved_output_tokens": self.reserved_output_tokens,
            "root": {
                "id": self.root.id,
                "layer": self.root.layer.value,
                "version": self.root.version,
            },
            "system_token_budget": self.system_token_budget,
            "version": self.version,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class PromptSelection:
    """Resolved profile and exact artifacts for one composition."""

    root: PromptArtifact
    packs: tuple[PromptArtifact, ...]
    profile: PromptProfile | None = None

    @property
    def digest(self) -> str | None:
        """Bind profile metadata to the exact selected artifact bodies."""

        if self.profile is None:
            return None
        payload = {
            "artifacts": [
                {
                    "body_sha256": hashlib.sha256(artifact.body.encode()).hexdigest(),
                    "id": artifact.id,
                    "layer": artifact.layer.value,
                    "version": artifact.version,
                }
                for artifact in (self.root, *self.packs)
            ],
            "profile_digest": self.profile.digest,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


class PromptBudgetExceededError(ValueError):
    """The selected prompt exceeded its reviewed profile budget."""

    def __init__(self, *, profile_id: str, estimate: int, budget: int) -> None:
        self.profile_id = profile_id
        self.estimate = estimate
        self.budget = budget
        super().__init__(
            f"prompt profile {profile_id!r} exceeds system token budget ({estimate} > {budget})"
        )


class PromptRequestBudgetExceededError(RuntimeError):
    """A finalized model request exceeded its exact profile budget."""

    def __init__(
        self,
        *,
        evidence: PromptProfileEvidence,
        estimate: int,
        budget: int,
        surface: str,
    ) -> None:
        self.prompt_profile_evidence = evidence
        self.estimate = estimate
        self.budget = budget
        self.surface = surface
        super().__init__(f"{surface} request exceeds prompt profile budget ({estimate} > {budget})")


def assembly_receipt(
    selection: PromptSelection,
    *,
    mode: PromptAssemblyMode,
    keys: tuple[str, ...],
    selected: tuple[int, ...],
    system_text: str,
    ablated: frozenset[int] = frozenset(),
) -> PromptAssemblyReceipt:
    """Bind one per-call conditional-pack decision to its exact profile and text.

    ``ablated`` pack indexes were removed by a reviewed ablation profile and are
    recorded there instead of as assembly exclusions.
    """

    profile = selection.profile
    if profile is None or len(profile.packs) != len(selection.packs):
        raise ValueError("prompt assembly requires one exact profile selection")
    chosen = frozenset(selected)
    if chosen & ablated:
        raise ValueError("prompt assembly cannot select an ablated pack")
    unselected = tuple(
        LayerRef(
            id=artifact.id,
            version=artifact.version,
            layer=artifact.layer,
            token_estimate=estimate_prompt_tokens(artifact.body),
        )
        for index, artifact in enumerate(selection.packs)
        if index not in chosen and index not in ablated
    )
    covered = tuple(sorted({key for index in chosen for key in profile.packs[index].covers}))
    ordered_keys = tuple(sorted(set(keys)))
    payload = {
        "keys": list(ordered_keys),
        "mode": mode.value,
        "profile_digest": selection.digest,
        "selected": [profile.packs[index].digest_payload() for index in sorted(chosen)],
        "system_text_sha256": hashlib.sha256(system_text.encode()).hexdigest(),
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return PromptAssemblyReceipt(
        mode=mode,
        keys=ordered_keys,
        unselected_layers=unselected,
        covered_keys=covered,
        governed_keys=profile.governed_keys,
        digest="sha256:" + hashlib.sha256(encoded.encode()).hexdigest(),
    )


def compose_static_selection(selection: PromptSelection) -> ComposedPrompt:
    """Compose catalog-only layers without runtime memory, tools, or skills.

    A dynamic profile composes every pack here; per-call selection belongs to
    :class:`fdai.core.prompts.assembly.PromptAssembler`.
    """

    artifacts = (selection.root, *selection.packs)
    system_text = "\n\n".join(artifact.body for artifact in artifacts)
    token_estimate = estimate_prompt_tokens(system_text)
    profile = selection.profile
    if profile is not None and token_estimate > profile.system_token_budget:
        raise PromptBudgetExceededError(
            profile_id=profile.id,
            estimate=token_estimate,
            budget=profile.system_token_budget,
        )
    return ComposedPrompt(
        system_text=system_text,
        layer_manifest=tuple(
            LayerRef(
                id=artifact.id,
                version=artifact.version,
                layer=artifact.layer,
                token_estimate=estimate_prompt_tokens(artifact.body),
            )
            for artifact in artifacts
        ),
        token_estimate=token_estimate,
        profile_id=profile.id if profile is not None else None,
        profile_version=profile.version if profile is not None else None,
        profile_digest=selection.digest,
        system_token_budget=profile.system_token_budget if profile is not None else None,
        request_token_budget=profile.request_token_budget if profile is not None else None,
        reserved_output_tokens=profile.reserved_output_tokens if profile is not None else None,
        assembly=(
            assembly_receipt(
                selection,
                mode=PromptAssemblyMode.COMPLETE,
                keys=(),
                selected=tuple(range(len(selection.packs))),
                system_text=system_text,
            )
            if profile is not None and profile.dynamic
            else None
        ),
    )


__all__ = [
    "assembly_receipt",
    "compose_static_selection",
    "PromptArtifactRef",
    "PromptBudgetExceededError",
    "PromptProfile",
    "PromptProfileMode",
    "PromptRequestBudgetExceededError",
    "PromptSelection",
]
