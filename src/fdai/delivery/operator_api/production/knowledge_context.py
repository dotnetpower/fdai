"""Production composition for read-only conversation knowledge context."""

from __future__ import annotations

from typing import Any

from fdai.delivery.operator_api.application.conversation.capabilities.knowledge_context import (
    KnowledgeContextChatTools,
)
from fdai.delivery.persistence import (
    PostgresOperatorMemoryProposalStore,
    PostgresOperatorMemoryProposalStoreConfig,
    PostgresOperatorMemoryStore,
    PostgresOperatorMemoryStoreConfig,
    PostgresPostTurnReviewLedger,
    PostgresPostTurnReviewLedgerConfig,
    PostgresSkillProposalStore,
    PostgresSkillProposalStoreConfig,
    PostgresSkillSourceRefreshStateStore,
    PostgresSkillSourceStore,
    PostgresSkillSourceStoreConfig,
)


def build_production_knowledge_context(
    *,
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    skill_disclosure: Any,
    user_memories: Any,
    skill_sources: Any = None,
) -> KnowledgeContextChatTools:
    source_config = PostgresSkillSourceStoreConfig(
        dsn=dsn,
        statement_timeout_ms=statement_timeout_ms,
        connect_timeout_s=connect_timeout_s,
    )
    return KnowledgeContextChatTools(
        skill_disclosure=skill_disclosure,
        skill_sources=(
            skill_sources.sources
            if skill_sources is not None
            else PostgresSkillSourceStore(config=source_config)
        ),
        skill_refresh_states=(
            skill_sources.refresh_states
            if skill_sources is not None
            else PostgresSkillSourceRefreshStateStore(config=source_config)
        ),
        user_memories=user_memories,
        post_turn_reviews=PostgresPostTurnReviewLedger(
            config=PostgresPostTurnReviewLedgerConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        ),
        memory_proposals=PostgresOperatorMemoryProposalStore(
            config=PostgresOperatorMemoryProposalStoreConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        ),
        operator_memories=PostgresOperatorMemoryStore(
            config=PostgresOperatorMemoryStoreConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        ),
        skill_proposals=PostgresSkillProposalStore(
            config=PostgresSkillProposalStoreConfig(
                dsn=dsn,
                statement_timeout_ms=statement_timeout_ms,
                connect_timeout_s=connect_timeout_s,
            )
        ),
    )


__all__ = ["build_production_knowledge_context"]
