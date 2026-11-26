from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _digest_for_seed(seed: str) -> str:
    script = textwrap.dedent(
        f"""
        import sys
        from datetime import UTC, datetime
        from pathlib import Path

        root = Path({str(_REPO_ROOT)!r})
        for rel in (
            "packages/service-contracts/src",
            "services/core-control-plane",
            "services/core-control-plane/src",
        ):
            sys.path.insert(0, str(root / rel))

        from fdai.core.rbac.roles import Role
        from fdai.delivery.promotion_attestation import (
            GovernancePromotionAttestation,
            attestation_from_json,
            promotion_attestation_digest,
        )
        from fdai.rule_catalog.schema.governance_review_authority import (
            GovernanceApproval,
            GovernanceChangeClass,
            GovernancePrincipal,
            GovernanceReviewRequest,
        )

        now = datetime(2026, 10, 5, tzinfo=UTC)
        revision = "a" * 40
        roles = frozenset({{Role.APPROVER, Role.OWNER}})
        attestation = GovernancePromotionAttestation(
            review=GovernanceReviewRequest(
                change_class=GovernanceChangeClass.OPERATOR_OVERRIDE_PROMOTION,
                author=GovernancePrincipal(oid="author", roles=roles),
                head_revision=revision,
                head_committed_at=now,
                approvals=(
                    GovernanceApproval(
                        approver=GovernancePrincipal(oid="b", roles=roles),
                        reviewed_revision=revision,
                        approved_at=now,
                        phishing_resistant=True,
                    ),
                ),
                co_author_oids=frozenset({{"co-author-1", "co-author-2", "co-author-3"}}),
                committer_oids=frozenset({{"committer-1", "committer-2", "committer-3"}}),
            ),
            action_type_id="remediate.tag-add",
            fdai_revision=revision,
            scenario_set_version="scenario-v1",
            evidence_digest="b" * 64,
            idempotency_key="override-promotion-request-1",
            nonce="nonce-1",
            request_fingerprint="f" * 64,
        )
        round_tripped = attestation_from_json(attestation.as_json())
        print(promotion_attestation_digest(attestation))
        print(promotion_attestation_digest(round_tripped))
        """
    )
    env = {**os.environ, "PYTHONHASHSEED": seed}
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and inline deterministic test body
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    first, second = completed.stdout.splitlines()
    assert first == second
    return first


def test_promotion_attestation_digest_is_hash_seed_stable() -> None:
    assert _digest_for_seed("1") == _digest_for_seed("7")
