"""PgVectorPatternLibrary - real :class:`PatternLibrary` on Postgres+pgvector.

Realizes
:class:`~fdai.core.tiers.t1_lightweight.tier.PatternLibrary` against
the ``t1_pattern_library`` table created by
``alembic/versions/20260706_0005_t1_pattern_library.py``. The in-memory
fake in :mod:`fdai.core.tiers.t1_lightweight.testing` mirrors the
same contract so tests and production stay swappable.

Notes on the wire choice:

- psycopg 3 is already a repo dep (see ``pyproject.toml`` W1.5/W1.6). No
  new package lands in the lockfile.
- pgvector text literal (``'[a,b,c]'::vector``) is used to bind the
  embedding - this keeps the adapter free of the optional ``pgvector``
  Python package and avoids a new dependency.
- Cosine distance operator ``<=>`` returns ``1 - cosine_similarity``;
  the adapter returns ``1 - distance`` so the score is comparable to
  :func:`~fdai.core.tiers.t1_lightweight.tier.cosine_similarity`.
- ``ivfflat.probes`` is set ``SET LOCAL`` per query so the composition
  root can tune recall vs latency via config without a REINDEX.

``core/`` never sees this module - the composition root binds it into
:class:`~fdai.core.tiers.t1_lightweight.tier.T1Tier`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fdai.core.tiers.t1_lightweight.contextual_reuse import OperationalCaseContext
from fdai.core.tiers.t1_lightweight.tier import (
    LearnedAction,
    PatternLibrary,
    SimilarityMatch,
)
from fdai.shared.providers.pattern_library_writer import PatternLibraryWriter

_LOGGER = logging.getLogger("fdai.persistence.pgvector_pattern_library")

_EMBEDDING_DIM: Final[int] = 384


def _encode_vector(values: Sequence[float]) -> str:
    """Serialize a float sequence into pgvector's text literal format.

    pgvector accepts ``'[a,b,c]'::vector`` on the wire; ``%g`` gives a
    stable, short representation that survives the round-trip without
    loss of any semantics the cosine distance cares about.
    """
    if len(values) != _EMBEDDING_DIM:
        raise ValueError(f"embedding dim MUST be {_EMBEDDING_DIM}; got {len(values)}")
    return "[" + ",".join(f"{float(v):.9g}" for v in values) + "]"


@dataclass(frozen=True, slots=True)
class PgVectorPatternLibraryConfig:
    """DSN + tuning knobs for the adapter."""

    dsn: str
    """psycopg 3 connection string, e.g.
    ``postgresql://user:password@host:5432/db?sslmode=require``."""

    statement_timeout_ms: int = 15_000
    """Applied via ``SET LOCAL`` on every operation; fails fast rather
    than blocking the event loop on a stuck query."""

    connect_timeout_s: int = 10
    """Bound the TCP + auth handshake so a dead DB fails fast instead of
    hanging the event loop for ~2 minutes on the kernel TCP retry budget
    (``statement_timeout`` only starts *after* connect succeeds)."""

    ivfflat_probes: int = 10
    """Query-time recall knob. Higher → more IVFFlat lists scanned per
    query (better recall, higher latency). pgvector defaults to 1; the
    Phase-2 baseline uses 10 for a small library."""


class PgVectorPatternLibrary(PatternLibrary, PatternLibraryWriter):
    """Async :class:`PatternLibrary` + :class:`PatternLibraryWriter` on ``t1_pattern_library``."""

    def __init__(self, *, config: PgVectorPatternLibraryConfig) -> None:
        if not config.dsn:
            raise ValueError("PgVectorPatternLibraryConfig.dsn MUST NOT be empty")
        if config.statement_timeout_ms < 1:
            raise ValueError("statement_timeout_ms MUST be >= 1")
        if config.connect_timeout_s < 1:
            raise ValueError("connect_timeout_s MUST be >= 1")
        if config.ivfflat_probes < 1:
            raise ValueError("ivfflat_probes MUST be >= 1")
        self._config = config

    # ------------------------------------------------------------------
    # PatternLibrary
    # ------------------------------------------------------------------

    async def search(
        self, query_vector: Sequence[float], *, k: int = 5
    ) -> tuple[SimilarityMatch, ...]:
        """Return the top-``k`` neighbours ranked by descending cosine similarity.

        Empty library → empty tuple (matches the fake's contract). The
        threshold + success-rate filters live in the T1 tier, not here;
        this method just serves the ranked candidates.
        """
        if k < 1:
            raise ValueError("k MUST be >= 1")
        literal = _encode_vector(query_vector)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            row_factory=dict_row,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                cur = await conn.execute(
                    """
                    SELECT signature,
                           rule_id,
                           action_type,
                           params,
                           source_incident_id,
                           historical_success_rate,
                           reuse_count,
                           operational_case,
                           1.0 - (embedding <=> %s::vector) AS score
                      FROM t1_pattern_library
                     ORDER BY embedding <=> %s::vector ASC
                     LIMIT %s
                    """,
                    (literal, literal, int(k)),
                )
                rows = await cur.fetchall()

        matches: list[SimilarityMatch] = []
        for row in rows:
            action = LearnedAction(
                signature=str(row["signature"]),
                rule_id=str(row["rule_id"]),
                action_type=str(row["action_type"]),
                params=_coerce_params(row["params"]),
                incident_id=str(row["source_incident_id"]),
                success_rate=float(row["historical_success_rate"]),
                reuse_count=int(row["reuse_count"]),
                operational_case=_coerce_operational_case(row["operational_case"]),
            )
            matches.append(SimilarityMatch(action=action, score=float(row["score"])))
        # ORDER BY the cosine-distance operator returns ascending distance
        # which is equivalent to descending similarity - but be defensive
        # in case a future rewrite reorders.
        matches.sort(key=lambda m: m.score, reverse=True)
        return tuple(matches)

    # ------------------------------------------------------------------
    # Seeding / maintenance (not part of the Protocol)
    # ------------------------------------------------------------------

    async def add(self, *, vector: Sequence[float], action: LearnedAction) -> None:
        """Insert or update one pattern by ``signature``.

        The signature is the natural key: the discovery loop uses it as
        the update handle so promotions / retirements do not create
        duplicates. Re-adding the same signature bumps the row in place
        without breaking the pgvector index.
        """
        literal = _encode_vector(vector)
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            async with conn.transaction():
                await self._set_session_knobs(conn)
                await conn.execute(
                    """
                    INSERT INTO t1_pattern_library
                        (signature, rule_id, action_type, params, embedding,
                         source_incident_id, historical_success_rate, reuse_count,
                         operational_case)
                    VALUES
                        (%s, %s, %s, %s::jsonb, %s::vector, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (signature) DO UPDATE SET
                        rule_id                 = EXCLUDED.rule_id,
                        action_type             = EXCLUDED.action_type,
                        params                  = EXCLUDED.params,
                        embedding               = EXCLUDED.embedding,
                        source_incident_id      = EXCLUDED.source_incident_id,
                        historical_success_rate = EXCLUDED.historical_success_rate,
                        reuse_count             = EXCLUDED.reuse_count,
                        operational_case        = EXCLUDED.operational_case
                    """,
                    (
                        action.signature,
                        action.rule_id,
                        action.action_type,
                        json.dumps(dict(action.params), default=str),
                        literal,
                        action.incident_id,
                        float(action.success_rate),
                        int(action.reuse_count),
                        _encode_operational_case(action.operational_case),
                    ),
                )

    async def upsert_pattern(
        self,
        *,
        vector: Sequence[float],
        action: LearnedAction,
    ) -> None:
        """Realize :class:`PatternLibraryWriter.upsert_pattern` - thin wrapper on :meth:`add`.

        Kept as a distinct method so the write seam stays explicit at
        call sites (the growth intake runner binds against the
        :class:`~fdai.shared.providers.pattern_library_writer.PatternLibraryWriter`
        Protocol, not this concrete class).
        """
        await self.add(vector=vector, action=action)

    async def count(self) -> int:
        """Return the number of persisted patterns (test / diagnostic use)."""
        async with await psycopg.AsyncConnection.connect(
            self._config.dsn,
            connect_timeout=self._config.connect_timeout_s,
        ) as conn:
            await self._set_session_knobs(conn)
            cur = await conn.execute("SELECT COUNT(*) FROM t1_pattern_library")
            row = await cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _set_session_knobs(self, conn: psycopg.AsyncConnection[Any]) -> None:
        # SET LOCAL does not accept parametrized values in Postgres; inline
        # the (validated int) knobs literally.
        timeout_ms = int(self._config.statement_timeout_ms)
        probes = int(self._config.ivfflat_probes)
        await conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        await conn.execute(f"SET LOCAL ivfflat.probes = {probes}")


def _coerce_params(value: Any) -> Mapping[str, Any]:
    """Round-trip the ``params`` JSONB column into a plain ``dict``."""
    if value is None:
        return {}
    if isinstance(value, str):
        loaded = json.loads(value)
        if not isinstance(loaded, dict):
            raise RuntimeError(
                f"t1_pattern_library.params MUST be a JSON object; got {type(loaded).__name__}"
            )
        return loaded
    if isinstance(value, dict):
        return dict(value)
    raise RuntimeError(f"t1_pattern_library.params has unexpected type {type(value).__name__}")


def _encode_operational_case(context: OperationalCaseContext | None) -> str | None:
    if context is None:
        return None
    value = asdict(context)
    value["evidence_cutoff"] = context.evidence_cutoff.isoformat()
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _coerce_operational_case(value: Any) -> OperationalCaseContext | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RuntimeError("t1_pattern_library.operational_case is invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("t1_pattern_library.operational_case MUST be a JSON object")
    fields = {
        "case_ref",
        "failure_fingerprint",
        "resource_type",
        "action_type",
        "required_topology_role",
        "graph_digest",
        "owner_digest",
        "evidence_cutoff",
    }
    if set(value) != fields:
        raise RuntimeError("t1_pattern_library.operational_case has unexpected fields")
    cutoff = value["evidence_cutoff"]
    if not isinstance(cutoff, str):
        raise RuntimeError("t1_pattern_library.operational_case cutoff MUST be a timestamp")
    try:
        evidence_cutoff = datetime.fromisoformat(cutoff)
        return OperationalCaseContext(
            case_ref=str(value["case_ref"]),
            failure_fingerprint=str(value["failure_fingerprint"]),
            resource_type=str(value["resource_type"]),
            action_type=str(value["action_type"]),
            required_topology_role=str(value["required_topology_role"]),
            graph_digest=str(value["graph_digest"]),
            owner_digest=str(value["owner_digest"]),
            evidence_cutoff=evidence_cutoff,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("t1_pattern_library.operational_case is invalid") from exc


__all__ = [
    "PgVectorPatternLibrary",
    "PgVectorPatternLibraryConfig",
]
