"""PostgreSQL + pgvector adapter for structured behavior knowledge."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, cast

import psycopg
from psycopg.rows import dict_row

from fdai.delivery.pgvector.knowledge import _encode_vector
from fdai.shared.providers.behavior_knowledge import (
    BehaviorAuthorityRole,
    BehaviorKnowledgeIndex,
    BehaviorMatchKind,
    BehaviorSearchResult,
    BehaviorSource,
    BehaviorSourceKind,
    BehaviorSourceValidator,
    BehaviorSpec,
    BehaviorStatus,
    Embedder,
)
from fdai.shared.providers.secret_provider import SecretProvider

_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class PgvectorBehaviorKnowledgeConfig:
    """Connection secret and bounded retrieval tuning."""

    dsn_secret: str
    spec_table: str = "behavior_spec"
    source_table: str = "behavior_source"
    embedding_dim: int = 384
    statement_timeout_ms: int = 15_000
    connect_timeout_s: int = 10
    ivfflat_probes: int = 10

    def __post_init__(self) -> None:
        if not self.dsn_secret:
            raise ValueError("dsn_secret MUST be non-empty")
        for name, value in (
            ("spec_table", self.spec_table),
            ("source_table", self.source_table),
        ):
            if not _IDENTIFIER_RE.fullmatch(value):
                raise ValueError(f"{name} MUST be a plain ASCII SQL identifier")
        if self.embedding_dim < 1:
            raise ValueError("embedding_dim MUST be >= 1")
        if self.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if self.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        if self.ivfflat_probes < 1:
            raise ValueError("ivfflat_probes MUST be >= 1")


class PgvectorBehaviorKnowledgeIndex(BehaviorKnowledgeIndex):
    """Persistent hybrid index over behavior contracts and source metadata."""

    def __init__(
        self,
        *,
        config: PgvectorBehaviorKnowledgeConfig,
        embedder: Embedder,
        secrets: SecretProvider,
        source_validator: BehaviorSourceValidator | None = None,
    ) -> None:
        self._config = config
        self._embedder = embedder
        self._secrets = secrets
        self._source_validator = source_validator

    async def upsert(self, spec: BehaviorSpec) -> bool:
        stored = spec
        if not stored.embedding:
            stored = replace(
                stored,
                embedding=tuple(await self._embedder.embed(spec.search_text())),
            )
        literal = _encode_vector(stored.embedding, dim=self._config.embedding_dim)
        content_hash = _content_hash(stored)
        dsn = await self._secrets.get(self._config.dsn_secret)
        spec_table = self._config.spec_table
        source_table = self._config.source_table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"SELECT content_hash FROM {spec_table} WHERE behavior_id = %s",  # noqa: S608
                    (stored.behavior_id,),
                )
                previous = await cursor.fetchone()
                await connection.execute(
                    f"""
                    INSERT INTO {spec_table} (
                        behavior_id, subject_kind, subject_id, status, owner,
                        question_aliases, trigger, preconditions, processing_steps,
                        outcomes, exclusions, safety, localized_content,
                        search_text, alias_search_text,
                        search_vector, embedding, indexed_commit, extractor_version,
                        source_manifest_hash, content_hash, test_backed, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb,
                        %s, %s,
                        to_tsvector('simple', %s), %s::vector, %s, %s,
                        %s, %s, %s, NOW()
                    )
                    ON CONFLICT (behavior_id) DO UPDATE SET
                        subject_kind = EXCLUDED.subject_kind,
                        subject_id = EXCLUDED.subject_id,
                        status = EXCLUDED.status,
                        owner = EXCLUDED.owner,
                        question_aliases = EXCLUDED.question_aliases,
                        trigger = EXCLUDED.trigger,
                        preconditions = EXCLUDED.preconditions,
                        processing_steps = EXCLUDED.processing_steps,
                        outcomes = EXCLUDED.outcomes,
                        exclusions = EXCLUDED.exclusions,
                        safety = EXCLUDED.safety,
                        localized_content = EXCLUDED.localized_content,
                        search_text = EXCLUDED.search_text,
                        alias_search_text = EXCLUDED.alias_search_text,
                        search_vector = EXCLUDED.search_vector,
                        embedding = EXCLUDED.embedding,
                        indexed_commit = EXCLUDED.indexed_commit,
                        extractor_version = EXCLUDED.extractor_version,
                        source_manifest_hash = EXCLUDED.source_manifest_hash,
                        content_hash = EXCLUDED.content_hash,
                        test_backed = EXCLUDED.test_backed,
                        updated_at = NOW()
                    """,  # noqa: S608
                    (
                        stored.behavior_id,
                        stored.subject_kind,
                        stored.subject_id,
                        stored.status,
                        stored.owner,
                        list(stored.question_aliases),
                        list(stored.trigger),
                        list(stored.preconditions),
                        list(stored.steps),
                        list(stored.outcomes),
                        list(stored.exclusions),
                        list(stored.safety),
                        json.dumps(_localized_payload(stored)),
                        stored.search_text(),
                        "\n".join(stored.question_aliases),
                        stored.search_text(),
                        literal,
                        stored.indexed_commit,
                        stored.extractor_version,
                        stored.source_manifest_hash,
                        content_hash,
                        stored.test_backed,
                    ),
                )
                await connection.execute(
                    f"DELETE FROM {source_table} WHERE behavior_id = %s",  # noqa: S608
                    (stored.behavior_id,),
                )
                for source in stored.sources:
                    await connection.execute(
                        f"""
                        INSERT INTO {source_table} (
                            behavior_id, source_kind, path, symbol, line_start,
                            line_end, blob_sha, authority_role
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,  # noqa: S608
                        (
                            stored.behavior_id,
                            source.source_kind,
                            source.path,
                            source.symbol,
                            source.line_start,
                            source.line_end,
                            source.blob_sha,
                            source.authority_role,
                        ),
                    )
        return previous is None or previous["content_hash"] != content_hash

    async def search(self, query: str, *, k: int = 5) -> Sequence[BehaviorSearchResult]:
        if k <= 0 or not query.strip():
            return ()
        query_vector = await self._embedder.embed(query)
        literal = _encode_vector(query_vector, dim=self._config.embedding_dim)
        dsn = await self._secrets.get(self._config.dsn_secret)
        spec_table = self._config.spec_table
        source_table = self._config.source_table
        async with await psycopg.AsyncConnection.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as connection:
            async with connection.transaction():
                await self._set_session_knobs(connection)
                cursor = await connection.execute(
                    f"""
                    WITH raw AS (
                        SELECT b.*,
                               EXISTS (
                                   SELECT 1
                                     FROM unnest(b.question_aliases) AS alias
                                    WHERE lower(alias) = lower(%s)
                               ) AS exact_alias,
                               strpos(lower(%s), lower(b.subject_id)) > 0 AS exact_identifier,
                               similarity(b.subject_id, %s) AS subject_score,
                               GREATEST(
                                   ts_rank_cd(b.search_vector, plainto_tsquery('simple', %s)),
                                   similarity(b.alias_search_text, %s)
                               ) AS lexical_score,
                               1.0 - (b.embedding <=> %s::vector) AS semantic_score
                          FROM {spec_table} AS b
                    ), ranked AS (
                        SELECT raw.*,
                               row_number() OVER (
                                   ORDER BY lexical_score DESC, behavior_id DESC
                               ) AS lexical_rank,
                               row_number() OVER (
                                   ORDER BY semantic_score DESC, behavior_id DESC
                               ) AS semantic_rank
                          FROM raw
                    )
                    SELECT ranked.*,
                           1.0 / (60.0 + lexical_rank)
                           + 1.0 / (60.0 + semantic_rank) AS fusion_score
                      FROM ranked
                     WHERE exact_alias
                        OR exact_identifier
                        OR lexical_score > 0
                        OR semantic_score > 0
                    ORDER BY exact_alias DESC,
                              exact_identifier DESC,
                              subject_score DESC,
                              ((status = 'implemented')::int + test_backed::int) DESC,
                              fusion_score DESC,
                              lexical_score DESC,
                              semantic_score DESC,
                              behavior_id DESC
                     LIMIT %s
                    """,  # noqa: S608
                    (query, query, query, query, query, literal, int(k)),
                )
                rows = await cursor.fetchall()
                behavior_ids = [str(row["behavior_id"]) for row in rows]
                sources = await self._load_sources(
                    connection,
                    source_table=source_table,
                    behavior_ids=behavior_ids,
                )

        results = []
        for row in rows:
            behavior_id = str(row["behavior_id"])
            spec_sources = tuple(sources.get(behavior_id, ()))
            spec = _row_to_spec(row, spec_sources)
            stale_sources = await self._stale_sources(spec_sources)
            match_kind: BehaviorMatchKind = (
                "exact_alias"
                if bool(row["exact_alias"])
                else "exact_identifier"
                if bool(row["exact_identifier"])
                else "hybrid"
            )
            results.append(
                BehaviorSearchResult(
                    spec=spec,
                    score=float(row["fusion_score"]),
                    match_kind=match_kind,
                    stale=bool(stale_sources),
                    stale_sources=stale_sources,
                )
            )
        return tuple(results)

    async def _load_sources(
        self,
        connection: psycopg.AsyncConnection[Any],
        *,
        source_table: str,
        behavior_ids: list[str],
    ) -> dict[str, list[BehaviorSource]]:
        if not behavior_ids:
            return {}
        cursor = await connection.execute(
            f"""
            SELECT behavior_id, source_kind, path, symbol, line_start,
                   line_end, blob_sha, authority_role
              FROM {source_table}
             WHERE behavior_id = ANY(%s)
             ORDER BY behavior_id, path, line_start, symbol
            """,  # noqa: S608
            (behavior_ids,),
        )
        grouped: dict[str, list[BehaviorSource]] = {}
        for row in await cursor.fetchall():
            grouped.setdefault(str(row["behavior_id"]), []).append(
                BehaviorSource(
                    source_kind=cast(BehaviorSourceKind, str(row["source_kind"])),
                    path=str(row["path"]),
                    symbol=str(row["symbol"]),
                    line_start=int(row["line_start"]),
                    line_end=int(row["line_end"]),
                    blob_sha=str(row["blob_sha"]),
                    authority_role=cast(BehaviorAuthorityRole, str(row["authority_role"])),
                )
            )
        return grouped

    async def _stale_sources(
        self,
        sources: tuple[BehaviorSource, ...],
    ) -> tuple[BehaviorSource, ...]:
        if self._source_validator is None:
            return ()
        stale = []
        for source in sources:
            if not (await self._source_validator.validate(source)).fresh:
                stale.append(source)
        return tuple(stale)

    async def _set_session_knobs(self, connection: psycopg.AsyncConnection[Any]) -> None:
        timeout_ms = int(self._config.statement_timeout_ms)
        probes = int(self._config.ivfflat_probes)
        await connection.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        await connection.execute(f"SET LOCAL ivfflat.probes = {probes}")


def _row_to_spec(row: Mapping[str, Any], sources: tuple[BehaviorSource, ...]) -> BehaviorSpec:
    return BehaviorSpec(
        behavior_id=str(row["behavior_id"]),
        subject_kind=str(row["subject_kind"]),
        subject_id=str(row["subject_id"]),
        status=cast(BehaviorStatus, str(row["status"])),
        owner=str(row["owner"]),
        question_aliases=tuple(str(item) for item in row["question_aliases"]),
        trigger=tuple(str(item) for item in row["trigger"]),
        preconditions=tuple(str(item) for item in row["preconditions"]),
        steps=tuple(str(item) for item in row["processing_steps"]),
        outcomes=tuple(str(item) for item in row["outcomes"]),
        exclusions=tuple(str(item) for item in row["exclusions"]),
        safety=tuple(str(item) for item in row["safety"]),
        localized=_localized_from_raw(row["localized_content"]),
        sources=sources,
        indexed_commit=str(row["indexed_commit"]),
        extractor_version=str(row["extractor_version"]),
        source_manifest_hash=str(row["source_manifest_hash"]),
    )


def _content_hash(spec: BehaviorSpec) -> str:
    payload = {
        "behavior_id": spec.behavior_id,
        "subject_kind": spec.subject_kind,
        "subject_id": spec.subject_id,
        "status": spec.status,
        "owner": spec.owner,
        "question_aliases": spec.question_aliases,
        "trigger": spec.trigger,
        "preconditions": spec.preconditions,
        "steps": spec.steps,
        "outcomes": spec.outcomes,
        "exclusions": spec.exclusions,
        "safety": spec.safety,
        "localized": _localized_payload(spec),
        "sources": [source.manifest_record() for source in spec.sources],
        "indexed_commit": spec.indexed_commit,
        "extractor_version": spec.extractor_version,
        "source_manifest_hash": spec.source_manifest_hash,
        "embedding": spec.embedding,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _localized_payload(spec: BehaviorSpec) -> dict[str, dict[str, tuple[str, ...]]]:
    return {
        locale: {
            "trigger": content.trigger,
            "preconditions": content.preconditions,
            "steps": content.steps,
            "outcomes": content.outcomes,
            "exclusions": content.exclusions,
            "safety": content.safety,
        }
        for locale, content in spec.localized.items()
    }


def _localized_from_raw(raw: Any) -> dict[str, Any]:
    from fdai.shared.providers.behavior_knowledge import BehaviorContent

    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, Mapping):
        return {}
    return {
        str(locale): BehaviorContent(
            trigger=tuple(str(item) for item in content.get("trigger", ())),
            preconditions=tuple(str(item) for item in content.get("preconditions", ())),
            steps=tuple(str(item) for item in content.get("steps", ())),
            outcomes=tuple(str(item) for item in content.get("outcomes", ())),
            exclusions=tuple(str(item) for item in content.get("exclusions", ())),
            safety=tuple(str(item) for item in content.get("safety", ())),
        )
        for locale, content in value.items()
        if isinstance(content, Mapping)
    }


__all__ = ["PgvectorBehaviorKnowledgeConfig", "PgvectorBehaviorKnowledgeIndex"]
