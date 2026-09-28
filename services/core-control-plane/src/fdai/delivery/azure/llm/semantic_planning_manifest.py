"""Replay-manifest helpers for Azure semantic planning prompts."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from fdai.core.prompts import estimate_prompt_tokens
from fdai.core.prompts.types import LayerRef, PromptLayer, PromptReplayManifest


def transmitted_prompt_manifest(
    manifest: PromptReplayManifest | None,
    *,
    system_content: str,
    schema: str,
) -> PromptReplayManifest | None:
    if manifest is None:
        return None
    return replace(
        manifest,
        system_text_sha256=sha256_hex(system_content),
        layer_manifest=(
            *manifest.layer_manifest,
            LayerRef(
                id="semantic-response-schema",
                version=1,
                layer=PromptLayer.ADAPTER_SCHEMA,
                token_estimate=estimate_prompt_tokens(schema),
            ),
        ),
        token_estimate=estimate_prompt_tokens(system_content),
    )


def validate_prompt_manifest(
    prompt: str | None,
    manifest: PromptReplayManifest | None,
) -> None:
    if manifest is None:
        return
    if prompt is None or manifest.system_text_sha256 != sha256_hex(prompt):
        raise ValueError("semantic planning prompt manifest does not match its system prompt")


def validate_output_reserve(
    name: str,
    manifest: PromptReplayManifest | None,
    required_tokens: int,
) -> None:
    if (
        manifest is not None
        and manifest.reserved_output_tokens is not None
        and manifest.reserved_output_tokens < required_tokens
    ):
        raise ValueError(f"{name} prompt output reserve is below configured max_tokens")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


__all__ = [
    "sha256_hex",
    "transmitted_prompt_manifest",
    "validate_output_reserve",
    "validate_prompt_manifest",
]
