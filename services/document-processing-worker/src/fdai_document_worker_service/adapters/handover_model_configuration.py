"""Explicit deployment-only reviewed handover model composition."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .handover import PostgresHandoverDraftStore
from .handover_model import AzureReviewedHandoverInterpreter, HandoverModelTarget


class _Target(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    endpoint: str
    deployment: str
    publisher: str
    family: str
    input_micros_per_million: Annotated[StrictInt, Field(ge=0)]
    output_micros_per_million: Annotated[StrictInt, Field(ge=0)]
    api_version: str = "2025-01-01-preview"


class _Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    author: _Target
    reviewer: _Target
    author_prompt_path: str
    author_prompt_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    reviewer_prompt_path: str
    reviewer_prompt_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("handover configuration has duplicate keys")
        values[key] = value
    return values


def _prompt(path: str, expected: str) -> str:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("handover prompt is unavailable")
    data = source.read_bytes()
    if not 1 <= len(data) <= 32_000 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("handover prompt does not match its reviewed digest")
    return data.decode("utf-8")


def build_handover_interpreter(
    *,
    environment: Mapping[str, str],
    credential: AsyncTokenCredential,
    client: httpx.AsyncClient,
    store: PostgresHandoverDraftStore,
) -> AzureReviewedHandoverInterpreter | None:
    raw = environment.get("FDAI_HANDOVER_MODELS_JSON", "").strip()
    if not raw:
        return None
    try:
        if len(raw.encode()) > 32_000:
            raise ValueError("handover model configuration is oversized")
        configuration = _Configuration.model_validate(
            json.loads(raw, object_pairs_hook=_unique_pairs)
        )
        for target in (configuration.author, configuration.reviewer):
            host = urlsplit(target.endpoint).hostname or ""
            if (
                not host.endswith(".openai.azure.com")
                or any(
                    character
                    not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
                    for character in target.deployment
                )
                or any(
                    character
                    not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
                    for character in target.api_version
                )
            ):
                raise ValueError("handover model token target is not an Azure OpenAI authority")
        return AzureReviewedHandoverInterpreter(
            author=HandoverModelTarget(**configuration.author.model_dump()),
            reviewer=HandoverModelTarget(**configuration.reviewer.model_dump()),
            credential=credential,
            client=client,
            reservations=store,
            author_prompt=_prompt(
                configuration.author_prompt_path, configuration.author_prompt_sha256
            ),
            reviewer_prompt=_prompt(
                configuration.reviewer_prompt_path, configuration.reviewer_prompt_sha256
            ),
        )
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ValueError(
            "reviewed handover model configuration is unavailable or invalid"
        ) from None
