from __future__ import annotations

from uuid import uuid4

import pytest

from fdai.core.stewardship.handover_bootstrap import (
    DraftOutcome,
    PersonRef,
    StewardMapDraft,
)
from fdai.delivery.ingestion_gateway.handover import (
    HandoverDraftArtifact,
    StateStoreHandoverDraftStore,
)
from fdai.shared.providers import DocumentNotFoundError
from fdai.shared.providers.testing.state_store import InMemoryStateStore


async def test_state_store_handover_draft_round_trips_across_instances() -> None:
    state = InMemoryStateStore()
    upload_id = uuid4()
    artifact = HandoverDraftArtifact(
        upload_id=upload_id,
        document_id=uuid4(),
        version_id=uuid4(),
        draft=StewardMapDraft(
            version=1,
            outcome=DraftOutcome.DRAFTED,
            unresolved_people=(PersonRef("Example Operator"),),
            unmapped_agents=("Odin",),
            warnings=("unresolved_people:1",),
        ),
        yaml="stewardship:\n  version: 1\n",
    )

    await StateStoreHandoverDraftStore(state_store=state).put(artifact)
    restored = await StateStoreHandoverDraftStore(state_store=state).get(upload_id)

    assert restored == artifact


async def test_state_store_handover_draft_missing_is_explicit() -> None:
    store = StateStoreHandoverDraftStore(state_store=InMemoryStateStore())

    with pytest.raises(DocumentNotFoundError):
        await store.get(uuid4())
