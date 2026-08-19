"""Grant Core runtime access to append-only question campaign ledgers."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_question_campaign_20260819"
down_revision: str | Sequence[str] | None = "core_incident_projection_20260819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

migration_owner = "core-control-plane"
owned_tables = (
    "question_campaign",
    "question_campaign_attempt",
    "question_campaign_case_claim",
    "question_campaign_completion",
)
rollback = {
    "strategy": "revoke-question-campaign-runtime-access",
    "restores": "core_incident_projection_20260819",
    "requires": "core-runtime-stopped",
}


def upgrade() -> None:
    op.execute("GRANT SELECT, INSERT ON TABLE question_campaign TO fdai_core")
    op.execute("GRANT SELECT, INSERT ON TABLE question_campaign_attempt TO fdai_core")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE question_campaign_case_claim TO fdai_core"
    )
    op.execute("GRANT SELECT, INSERT ON TABLE question_campaign_completion TO fdai_core")


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT ON TABLE question_campaign_completion FROM fdai_core")
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE question_campaign_case_claim FROM fdai_core"
    )
    op.execute("REVOKE SELECT, INSERT ON TABLE question_campaign_attempt FROM fdai_core")
    op.execute("REVOKE SELECT, INSERT ON TABLE question_campaign FROM fdai_core")
