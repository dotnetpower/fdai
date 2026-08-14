"""include usage scope in LLM invocation identity

Revision ID: 20260814_0082
Revises: 20260813_0081
Create Date: 2026-08-14 00:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260814_0082"
down_revision: str | None = "20260813_0081"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_COLUMNS = (
    "occurred_at",
    "correlation_id",
    "capability_id",
    "model_key",
    "tier",
    "mode",
    "prompt_tokens",
    "completion_tokens",
)
_SCOPED_COLUMNS = (*_LEGACY_COLUMNS[:6], "usage_scope", *_LEGACY_COLUMNS[6:])


def _replace_identity(columns: tuple[str, ...]) -> None:
    expected = ", ".join(f"'{column}'" for column in _LEGACY_COLUMNS)
    replacement = ", ".join(columns)
    op.execute(
        f"""
        DO $$
        DECLARE
            identity_constraint TEXT;
        BEGIN
            SELECT constraint_record.conname
              INTO identity_constraint
              FROM pg_constraint AS constraint_record
             WHERE constraint_record.conrelid = 'llm_invocation'::regclass
               AND constraint_record.contype = 'u'
               AND ARRAY(
                SELECT attribute.attname::TEXT
                      FROM unnest(constraint_record.conkey)
                           WITH ORDINALITY AS key_column(attnum, position)
                      JOIN pg_attribute AS attribute
                        ON attribute.attrelid = constraint_record.conrelid
                       AND attribute.attnum = key_column.attnum
                     ORDER BY key_column.position
               ) = ARRAY[{expected}];

            IF identity_constraint IS NULL THEN
                RAISE EXCEPTION 'legacy llm_invocation identity constraint is missing';
            END IF;

            EXECUTE format(
                'ALTER TABLE llm_invocation DROP CONSTRAINT %I',
                identity_constraint
            );
        END $$;

        ALTER TABLE llm_invocation
            ADD CONSTRAINT uq_llm_invocation_identity
            UNIQUE ({replacement});
        """
    )


def upgrade() -> None:
    _replace_identity(_SCOPED_COLUMNS)


def downgrade() -> None:
    op.execute("ALTER TABLE llm_invocation DROP CONSTRAINT uq_llm_invocation_identity;")
    legacy_columns = ", ".join(_LEGACY_COLUMNS)
    op.execute(
        f"""
        ALTER TABLE llm_invocation
            ADD CONSTRAINT llm_invocation_legacy_identity
            UNIQUE ({legacy_columns});
        """
    )
