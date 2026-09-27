"""Per-call conditional-pack assembly for exact prompt profiles."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterable

from fdai.core.prompts.budget import estimate_prompt_tokens
from fdai.core.prompts.profiles import (
    PromptBudgetExceededError,
    PromptProfile,
    PromptSelection,
    assembly_receipt,
)
from fdai.core.prompts.types import (
    AblatedLayerRef,
    ComposedPrompt,
    LayerRef,
    PromptAblationProfileName,
    PromptAssemblyMode,
    validate_assembly_keys,
)

_LAYER_JOIN = "\n\n"
_MAX_CACHED_SELECTIONS = 64


class PromptAssembler:
    """Compose one exact profile per call from typed assembly keys.

    Construction validates the complete selection against the profile budget, so
    every per-call subset is within budget too. Keys are derived by callers from
    typed, validated upstream state and never from raw language. ``None`` or keys
    that select no conditional pack yield the complete composition, which equals
    the static composition of the same profile.
    """

    def __init__(
        self,
        selection: PromptSelection,
        *,
        ablation_profile: PromptAblationProfileName = PromptAblationProfileName.NONE,
        ablated_layers: tuple[AblatedLayerRef, ...] = (),
        ablated_indexes: frozenset[int] = frozenset(),
    ) -> None:
        profile = selection.profile
        if profile is None or len(profile.packs) != len(selection.packs):
            raise ValueError("prompt assembly requires one exact prompt profile")
        if any(not 0 <= index < len(selection.packs) for index in ablated_indexes):
            raise ValueError("prompt assembly ablated indexes MUST name profile packs")
        self._selection = selection
        self._profile: PromptProfile = profile
        self._ablation_profile = ablation_profile
        self._ablated_layers = ablated_layers
        self._ablated = ablated_indexes
        self._available = tuple(
            index for index in range(len(selection.packs)) if index not in ablated_indexes
        )
        self._lock = threading.Lock()
        self._texts: OrderedDict[tuple[int, ...], tuple[str, tuple[LayerRef, ...], int]] = (
            OrderedDict()
        )
        self._complete = self._compose(self._available, mode=PromptAssemblyMode.COMPLETE, keys=())

    @property
    def profile(self) -> PromptProfile:
        """The exact profile every assembled prompt is bound to."""

        return self._profile

    @property
    def dynamic(self) -> bool:
        """True when the profile declares at least one conditional pack."""

        return self._profile.dynamic

    @property
    def complete(self) -> ComposedPrompt:
        """The complete composition used as the safe fallback."""

        return self._complete

    def assemble(self, keys: Iterable[str] | None) -> ComposedPrompt:
        """Return the composition selected by ``keys`` or the complete fallback."""

        if not self.dynamic or keys is None:
            return self._complete
        requested = tuple(sorted(set(keys)))
        validate_assembly_keys(requested, name="keys")
        wanted = frozenset(requested)
        packs = self._profile.packs
        selected = tuple(
            index
            for index in self._available
            if not packs[index].conditional or wanted.intersection(packs[index].when_any)
        )
        if not any(packs[index].conditional for index in selected):
            return self._compose(self._available, mode=PromptAssemblyMode.COMPLETE, keys=requested)
        return self._compose(selected, mode=PromptAssemblyMode.SELECTED, keys=requested)

    def _compose(
        self,
        selected: tuple[int, ...],
        *,
        mode: PromptAssemblyMode,
        keys: tuple[str, ...],
    ) -> ComposedPrompt:
        text, layers, estimate = self._text(selected)
        profile = self._profile
        if estimate > profile.system_token_budget:
            raise PromptBudgetExceededError(
                profile_id=profile.id,
                estimate=estimate,
                budget=profile.system_token_budget,
            )
        return ComposedPrompt(
            system_text=text,
            layer_manifest=layers,
            token_estimate=estimate,
            profile_id=profile.id,
            profile_version=profile.version,
            profile_digest=self._selection.digest,
            system_token_budget=profile.system_token_budget,
            request_token_budget=profile.request_token_budget,
            reserved_output_tokens=profile.reserved_output_tokens,
            ablation_profile=self._ablation_profile,
            ablated_layers=self._ablated_layers,
            assembly=(
                assembly_receipt(
                    self._selection,
                    mode=mode,
                    keys=keys,
                    selected=selected,
                    system_text=text,
                    ablated=self._ablated,
                )
                if profile.dynamic
                else None
            ),
        )

    def _text(self, selected: tuple[int, ...]) -> tuple[str, tuple[LayerRef, ...], int]:
        with self._lock:
            cached = self._texts.get(selected)
            if cached is not None:
                self._texts.move_to_end(selected)
                return cached
        artifacts = (self._selection.root, *(self._selection.packs[index] for index in selected))
        text = _LAYER_JOIN.join(artifact.body for artifact in artifacts)
        layers = tuple(
            LayerRef(
                id=artifact.id,
                version=artifact.version,
                layer=artifact.layer,
                token_estimate=estimate_prompt_tokens(artifact.body),
            )
            for artifact in artifacts
        )
        value = (text, layers, estimate_prompt_tokens(text))
        with self._lock:
            self._texts[selected] = value
            while len(self._texts) > _MAX_CACHED_SELECTIONS:
                self._texts.popitem(last=False)
        return value


__all__ = ["PromptAssembler"]
