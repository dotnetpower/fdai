"""Evaluate or read observer recommendations; never install or manufacture evidence."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from fdai_service_contracts.observer_deployment import (
    ObserverDeploymentContext,
    ObserverDeploymentProposal,
)

from fdai.delivery.kubernetes_connector_planning import propose_observer_deployment
from fdai.delivery.kubernetes_connector_proposals import (
    ObserverDeploymentProposalService,
    StateStoreObserverConstraints,
)
from fdai.delivery.kubernetes_connector_runtime import (
    private_file,
    validate_connector_database_venue,
)
from fdai.delivery.persistence import PostgresStateStore, PostgresStateStoreConfig


async def _current(target_ref: str) -> ObserverDeploymentProposal | None:
    dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
    validate_connector_database_venue(dsn)
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    service = ObserverDeploymentProposalService(
        store, constraints=StateStoreObserverConstraints(store), now=lambda: datetime.now(UTC)
    )
    async with asyncio.timeout(10):
        return await service.current(target_ref)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operations = parser.add_subparsers(dest="operation", required=True)
    evaluate = operations.add_parser("evaluate")
    evaluate.add_argument("--context", type=Path, required=True)
    show = operations.add_parser("show")
    show.add_argument("--target-ref", required=True)
    args = parser.parse_args(argv)
    proposal: ObserverDeploymentProposal | None
    try:
        if args.operation == "evaluate":
            context = ObserverDeploymentContext.model_validate_json(private_file(args.context))
            proposal = propose_observer_deployment(context, now=datetime.now(UTC))
        else:
            proposal = asyncio.run(_current(args.target_ref))
        if proposal is None:
            print(
                json.dumps(
                    {
                        "status": "unavailable",
                        "reason": "observer_proposal_not_found",
                        "execution_authority": False,
                    }
                )
            )
            return 1
        print(proposal.model_dump_json())
        return 0
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        print(
            json.dumps(
                {
                    "status": "unavailable",
                    "reason": "observer_proposal_evidence_or_read_failed",
                    "execution_authority": False,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
