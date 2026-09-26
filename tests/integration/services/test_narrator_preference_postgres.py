"""Real SQL restart and revision-fence proof when the supported loopback fixture is set."""

from __future__ import annotations

import asyncio
import hashlib
import json
import runpy
from pathlib import Path

import pytest
from fdai_operator_service.families.iam.contracts import ModelPreferenceCommand
from fdai_operator_service.families.iam.errors import IamConflictError
from fdai_operator_service.model_lifecycle_startup import (
    ConfiguredResolvedModelsSource,
    OperatorResolvedModelsRevisionOwner,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreConfig,
)
from fdai_operator_service.postgres_iam import PostgresIamAdapters

_support = runpy.run_path(str(Path(__file__).with_name("test_assignment_receipt_postgres.py")))
database = _support["database"]
_role = _support["_role"]
pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_narrator_preference_commits_with_audit_and_survives_new_connection(
    database: str,
) -> None:
    content = json.dumps(
        {
            "capabilities": [],
            "narrator_candidates": [
                {"endpoint": "https://example.openai.azure.com", "deployment": "pinned"}
            ],
        }
    )
    owner = OperatorResolvedModelsRevisionOwner(
        ConfiguredResolvedModelsSource(content), hashlib.sha256(content.encode()).hexdigest()
    )
    await owner.start()
    config = PostgresFamilyStoreConfig(dsn=_role(database, "fdai_operator"))
    first = PostgresIamAdapters(PostgresFamilyStore(config), narrator_revision_owner=owner)
    command = ModelPreferenceCommand("principal-a", "pinned", 0)
    await first.set_preference(command)

    restarted = PostgresIamAdapters(PostgresFamilyStore(config), narrator_revision_owner=owner)
    assert (await restarted._narrator_preference("principal-a")).deployment == "pinned"
    assert (await restarted._narrator_preference("principal-b")).revision == 0
    with pytest.raises(IamConflictError, match="revision conflict"):
        await restarted.set_preference(command)
    results = await asyncio.gather(
        restarted.set_preference(ModelPreferenceCommand("principal-a", "auto", 1)),
        restarted.set_preference(ModelPreferenceCommand("principal-a", "pinned", 1)),
        return_exceptions=True,
    )
    assert sum(isinstance(result, IamConflictError) for result in results) == 1
    assert sum(result is None for result in results) == 1
    assert (await restarted._narrator_preference("principal-a")).revision == 2
    page = await restarted.store.read_state_page(prefix="operator-proposal:iam:", limit=100)
    accepted = [
        record.value
        for record in page.records
        if record.value.get("operation") == "model-settings.preference"
    ]
    assert len(accepted) == 2
    assert all(record["principal_id"] == "principal-a" for record in accepted)
