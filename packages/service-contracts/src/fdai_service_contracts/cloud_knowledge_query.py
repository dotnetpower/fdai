"""Inert model-proposed retrieval terms, separate from cloud applicability and authority."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, field_validator

from fdai_service_contracts.ontology_query import QueryContract, content_digest


class DocumentRetrievalQuery(QueryContract):
    """Bounded English search terms, not an intent, filter, instruction, or approval.

    The existing semantic judgment model supplies these terms. Callers bind them to
    the exact original utterance before retrieval; neither this DTO nor its digest
    establishes translation fidelity, source truth, or execution authority.
    """

    model_config = ConfigDict(str_strip_whitespace=False, revalidate_instances="always")

    query_text: Annotated[
        str,
        Field(
            min_length=1,
            max_length=512,
            strict=True,
            description=(
                "English plain-text retrieval terms for the supplied utterance. Preserve "
                "numbers, units, identifiers and negation. Do not fabricate SKU, API-version, "
                "region, resource, applicability or source conditions. No markup, links, "
                "instructions, filters or authority; at most 512 characters."
            ),
        ),
    ]
    source_locale: Literal["en", "ko"]
    target_locale: Literal["en"] = "en"
    execution_authority: Literal[False] = False

    @field_validator("query_text")
    @classmethod
    def _plain_query(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("document retrieval query MUST be trimmed")
        if any(
            unicodedata.category(character).startswith("C")
            or (character.isspace() and character != " ")
            for character in value
        ):
            raise ValueError("document retrieval query MUST NOT contain control characters")
        if "://" in value or any(character in value for character in "<>[]{}\\`*#|~"):
            raise ValueError("document retrieval query MUST NOT contain links or markup")
        return value

    @field_validator("execution_authority", mode="before")
    @classmethod
    def _no_authority(cls, value: object) -> Literal[False]:
        if value is not False:
            raise ValueError("document retrieval query MUST NOT carry execution authority")
        return False

    def binding_digest(self, *, utterance: str) -> str:
        """Commit to this DTO and exact source text without storing a second copy.

        Word order, case, whitespace and locale remain identity-bearing. A digest
        is a replay binding only; the caller still needs an accepted judgment.
        """

        return content_digest(
            {
                "document_query": self.model_dump(mode="json"),
                "source_utterance_digest": content_digest({"utterance": utterance}),
            }
        )


__all__ = ["DocumentRetrievalQuery"]
