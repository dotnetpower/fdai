"""user context, proactive briefing, and workflow ownership stores

Revision ID: 20260716_0019
Revises: 20260716_0018
Create Date: 2026-07-16 14:15:00+09:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0019"
down_revision: str | None = "20260716_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE conversation_record (
            principal_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            last_active TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
            PRIMARY KEY (principal_id, conversation_id),
            CHECK (last_active >= started_at)
        );
        CREATE INDEX ix_conversation_record_recent
            ON conversation_record (principal_id, last_active DESC);

        CREATE TABLE conversation_turn (
            principal_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            turn_index INTEGER NOT NULL CHECK (turn_index >= 0),
            role TEXT NOT NULL CHECK (role IN ('operator', 'assistant', 'tool', 'system')),
            content TEXT NOT NULL CHECK (btrim(content) <> ''),
            recorded_at TIMESTAMPTZ NOT NULL,
            idempotency_key TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (principal_id, turn_id),
            UNIQUE (principal_id, conversation_id, turn_index),
            UNIQUE (principal_id, idempotency_key),
            FOREIGN KEY (principal_id, conversation_id)
                REFERENCES conversation_record(principal_id, conversation_id)
                ON DELETE CASCADE
        );
        CREATE INDEX ix_conversation_turn_history
            ON conversation_turn (principal_id, conversation_id, turn_index);

        CREATE TABLE user_preference (
            principal_id TEXT PRIMARY KEY,
            locale TEXT NOT NULL CHECK (locale IN ('en', 'ko')),
            verbosity TEXT NOT NULL CHECK (verbosity IN ('concise', 'detailed')),
            timezone TEXT,
            share_with_learner BOOLEAN NOT NULL DEFAULT FALSE,
            revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            updated_at TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE user_memory_fact (
            principal_id TEXT NOT NULL,
            memory_id TEXT NOT NULL,
            category TEXT NOT NULL CHECK (category IN ('preference', 'context', 'goal')),
            body TEXT NOT NULL CHECK (btrim(body) <> ''),
            source_turn_id TEXT NOT NULL,
            consented_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ,
            superseded_by TEXT,
            PRIMARY KEY (principal_id, memory_id),
            FOREIGN KEY (principal_id, source_turn_id)
                REFERENCES conversation_turn(principal_id, turn_id)
                ON DELETE CASCADE,
            FOREIGN KEY (principal_id, superseded_by)
                REFERENCES user_memory_fact(principal_id, memory_id),
            CHECK (expires_at IS NULL OR expires_at > created_at),
            CHECK (superseded_by IS NULL OR superseded_by <> memory_id)
        );
        CREATE INDEX ix_user_memory_active
            ON user_memory_fact (principal_id, created_at)
            WHERE superseded_by IS NULL;

        CREATE TABLE conversation_policy (
            principal_id TEXT NOT NULL,
            policy_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('opening_briefing', 'response_defaults')),
            enabled BOOLEAN NOT NULL,
            revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            confirmed_at TIMESTAMPTZ NOT NULL,
            source_turn_id TEXT NOT NULL,
            briefing_spec JSONB,
            response_defaults JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (principal_id, policy_id),
            FOREIGN KEY (principal_id, source_turn_id)
                REFERENCES conversation_turn(principal_id, turn_id)
                ON DELETE CASCADE,
            CHECK (
                (kind = 'opening_briefing' AND briefing_spec IS NOT NULL
                    AND response_defaults = '{}'::jsonb)
                OR
                (kind = 'response_defaults' AND briefing_spec IS NULL)
            )
        );

        CREATE TABLE briefing_subscription (
            principal_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL,
            name TEXT NOT NULL,
            spec JSONB NOT NULL,
            cron_expression TEXT NOT NULL,
            timezone TEXT NOT NULL,
            delivery_modes JSONB NOT NULL,
            channel_binding_ref TEXT,
            enabled BOOLEAN NOT NULL,
            next_run_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            max_lateness_seconds INTEGER NOT NULL CHECK (max_lateness_seconds >= 0),
            revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            lease_owner TEXT,
            lease_until TIMESTAMPTZ,
            PRIMARY KEY (principal_id, subscription_id)
        );
        CREATE INDEX ix_briefing_subscription_due
            ON briefing_subscription (next_run_at)
            WHERE enabled;

        CREATE TABLE briefing_run (
            principal_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            subscription_id TEXT,
            conversation_id TEXT,
            scheduled_for TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'partial', 'failed')),
            idempotency_key TEXT NOT NULL,
            title TEXT NOT NULL,
            body_markdown TEXT NOT NULL,
            item_count INTEGER NOT NULL CHECK (item_count >= 0),
            evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            source_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
            PRIMARY KEY (principal_id, run_id),
            UNIQUE (principal_id, idempotency_key),
            CHECK (subscription_id IS NOT NULL OR conversation_id IS NOT NULL)
        );
        CREATE INDEX ix_briefing_run_recent
            ON briefing_run (principal_id, started_at DESC);

        CREATE TABLE workflow_definition (
            definition_id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            workflow_version TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            definition_hash TEXT NOT NULL,
            action_catalog_digest TEXT NOT NULL,
            resolved_action_versions JSONB NOT NULL,
            workflow_document JSONB NOT NULL,
            origin TEXT NOT NULL CHECK (origin IN ('upstream', 'tenant', 'user')),
            visibility TEXT NOT NULL CHECK (visibility IN ('global', 'team', 'private')),
            lifecycle TEXT NOT NULL CHECK (
                lifecycle IN ('draft', 'validated', 'shadow', 'published', 'suspended', 'retired')
            ),
            owner_ref TEXT,
            derived_from TEXT REFERENCES workflow_definition(definition_id),
            source_ref TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (workflow_name, workflow_version, definition_hash),
            CHECK (origin <> 'user' OR owner_ref IS NOT NULL),
            CHECK (visibility <> 'private' OR owner_ref IS NOT NULL)
        );
        CREATE INDEX ix_workflow_definition_catalog
            ON workflow_definition (origin, visibility, lifecycle, workflow_name);

        CREATE TABLE workflow_binding (
            principal_id TEXT NOT NULL,
            binding_id TEXT NOT NULL,
            definition_id TEXT NOT NULL REFERENCES workflow_definition(definition_id),
            trigger TEXT NOT NULL CHECK (trigger IN ('deck_open', 'schedule', 'signal')),
            enabled BOOLEAN NOT NULL,
            scope_ref TEXT,
            cron_expression TEXT,
            timezone TEXT,
            signal_type TEXT,
            parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            revision BIGINT NOT NULL DEFAULT 1 CHECK (revision >= 1),
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (principal_id, binding_id),
            CHECK (
                (trigger = 'schedule' AND cron_expression IS NOT NULL AND timezone IS NOT NULL)
                OR
                (trigger <> 'schedule' AND cron_expression IS NULL AND timezone IS NULL)
            ),
            CHECK (
                (trigger = 'signal' AND signal_type IS NOT NULL)
                OR
                (trigger <> 'signal' AND signal_type IS NULL)
            )
        );
        CREATE INDEX ix_workflow_binding_principal
            ON workflow_binding (principal_id, enabled, trigger);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_binding;")
    op.execute("DROP TABLE IF EXISTS workflow_definition;")
    op.execute("DROP TABLE IF EXISTS briefing_run;")
    op.execute("DROP TABLE IF EXISTS briefing_subscription;")
    op.execute("DROP TABLE IF EXISTS conversation_policy;")
    op.execute("DROP TABLE IF EXISTS user_memory_fact;")
    op.execute("DROP TABLE IF EXISTS user_preference;")
    op.execute("DROP TABLE IF EXISTS conversation_turn;")
    op.execute("DROP TABLE IF EXISTS conversation_record;")
