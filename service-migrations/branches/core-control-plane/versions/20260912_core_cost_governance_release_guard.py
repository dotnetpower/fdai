"""Repair Cost Governance upgrade and retained-release rollback evaluation."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_cost_governance_release_guard_20260912"
down_revision: str | Sequence[str] | None = "core_cost_governance_w7_lifecycle_20260912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "cost_governance_lifecycle_receipt",
    "vertical_package_activation",
)
rollback = {
    "strategy": "restore-prior-cost-governance-release-guard",
    "restores": "core_cost_governance_w7_lifecycle_20260912",
    "requires": "cost-governance-lifecycle-writers-stopped",
}


def upgrade() -> None:
    """Disambiguate JSONB subtraction before evaluating upgrade or rollback."""

    op.execute(
        r"""
        DO $repair$
        DECLARE
            function_identity REGPROCEDURE := (
                'public.fdai_register_cost_governance_release('
                'text,text,text,text,text,text,text,text,text,text,'
                'text,text,bigint,text,jsonb)'
            )::REGPROCEDURE;
            function_definition TEXT;
            broken_expression TEXT := (
                'receipt.payload -> ''revision_pin'' - ''activation_revision'''
            );
            fixed_expression TEXT := (
                '(receipt.payload -> ''revision_pin'') - ''activation_revision'''
            );
            occurrence_count INTEGER;
        BEGIN
            SELECT pg_get_functiondef(function_identity)
              INTO function_definition;
            occurrence_count := (
                length(function_definition)
                - length(replace(function_definition, broken_expression, ''))
            ) / length(broken_expression);
            IF occurrence_count <> 1 OR position(fixed_expression IN function_definition) > 0 THEN
                RAISE EXCEPTION 'Cost Governance release guard repair source mismatch';
            END IF;
            EXECUTE replace(function_definition, broken_expression, fixed_expression);
        END;
        $repair$;
        """
    )


def downgrade() -> None:
    """Restore the previous release guard after lifecycle writers stop."""

    op.execute(
        r"""
        DO $restore$
        DECLARE
            function_identity REGPROCEDURE := (
                'public.fdai_register_cost_governance_release('
                'text,text,text,text,text,text,text,text,text,text,'
                'text,text,bigint,text,jsonb)'
            )::REGPROCEDURE;
            function_definition TEXT;
            broken_expression TEXT := (
                'receipt.payload -> ''revision_pin'' - ''activation_revision'''
            );
            fixed_expression TEXT := (
                '(receipt.payload -> ''revision_pin'') - ''activation_revision'''
            );
            occurrence_count INTEGER;
        BEGIN
            SELECT pg_get_functiondef(function_identity)
              INTO function_definition;
            occurrence_count := (
                length(function_definition)
                - length(replace(function_definition, fixed_expression, ''))
            ) / length(fixed_expression);
            IF occurrence_count <> 1 OR position(broken_expression IN function_definition) > 0 THEN
                RAISE EXCEPTION 'Cost Governance release guard restore source mismatch';
            END IF;
            EXECUTE replace(function_definition, fixed_expression, broken_expression);
        END;
        $restore$;
        """
    )
