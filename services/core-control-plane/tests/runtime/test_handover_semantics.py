"""Production semantic bindings use real source adapters without startup provider I/O."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fdai.agents import AssignmentWorkflowBindings
from fdai.delivery.identity.handover_envelopes import HandoverEnvelopeReader
from fdai.delivery.persistence.postgres import PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_handover_admission import PostgresHandoverSourceReader
from fdai.rule_catalog.pipeline.distill.handover_semantics import (
    HandoverSemanticCompilation,
    HandoverSemanticReview,
)
from fdai.runtime.handover_semantics import bind_handover_semantics
from fdai.runtime.venue import ExecutionVenueError
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.distiller import AbstainingDistiller

ROOT = Path(__file__).resolve().parents[4]


def arguments(tmp_path):
    workflow = AssignmentWorkflowBindings(AsyncMock(), AsyncMock(), SimpleNamespace())
    source = PostgresHandoverSourceReader(
        PostgresStateStoreConfig(dsn="host=127.0.0.1 dbname=example")
    )
    return {
        "workflow": workflow,
        "core": SimpleNamespace(source=source, admission=SimpleNamespace()),
        "container": SimpleNamespace(
            schema_registry=PackageResourceSchemaRegistry(),
            distiller=AbstainingDistiller(),
            ontology_object_types=(),
            ontology_link_types=(),
        ),
        "catalog_root": ROOT / "rule-catalog",
        "ontology_release": SimpleNamespace(digest="sha256:" + "a" * 64),
        "action_types": (),
        "environment": {
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_LOCAL_DOCUMENT_STORE_DIR": str(tmp_path),
        },
        "http_client": None,
        "identity": None,
    }


def test_actual_local_binder_installs_distinct_owner_readers_without_provider_io(tmp_path):
    inputs = arguments(tmp_path)
    result = bind_handover_semantics(**inputs)
    assert isinstance(result.semantic_compiler, HandoverSemanticCompilation)
    assert isinstance(result.semantic_reviewer, HandoverSemanticReview)
    assert result.semantic_compiler.sources is not result.semantic_reviewer.sources
    assert isinstance(result.semantic_compiler.sources.envelopes, HandoverEnvelopeReader)
    assert result.semantic_compiler.sources.envelopes.local_root == tmp_path
    assert result.semantic_compiler.packages is result.semantic_reviewer.packages
    assert not hasattr(result.semantic_reviewer, "distiller")
    assert result.validate is inputs["workflow"].validate


@pytest.mark.parametrize("missing", ["core", "ontology_release", "local_root", "venue"])
def test_missing_runtime_prerequisite_does_not_bind_partial_semantics(tmp_path, missing):
    inputs = arguments(tmp_path)
    if missing == "local_root":
        inputs["environment"].pop("FDAI_LOCAL_DOCUMENT_STORE_DIR")
    elif missing == "venue":
        inputs["environment"].pop("FDAI_EXECUTION_VENUE")
    else:
        inputs[missing] = None
    assert bind_handover_semantics(**inputs) is inputs["workflow"]


@pytest.mark.parametrize("venue", ["unexpected", "LOCAL", "staging"])
def test_unknown_venue_fails_before_selecting_a_document_source(tmp_path, venue):
    inputs = arguments(tmp_path)
    inputs["environment"]["FDAI_EXECUTION_VENUE"] = venue
    with pytest.raises(ExecutionVenueError):
        bind_handover_semantics(**inputs)


@pytest.mark.parametrize("venue", ["deployed", None, ""])
async def test_deployed_source_uses_read_identity_and_never_local_fallback(tmp_path, venue):
    inputs = arguments(tmp_path)
    inputs["environment"].update(
        FDAI_ADLS_ACCOUNT_URL="https://example.dfs.core.windows.net",
    )
    if venue is None:
        inputs["environment"].pop("FDAI_EXECUTION_VENUE")
    else:
        inputs["environment"]["FDAI_EXECUTION_VENUE"] = venue
    assert bind_handover_semantics(**inputs) is inputs["workflow"]
    requests = []

    async def handler(request):
        requests.append(request)
        raise AssertionError("startup must not call the provider")

    identity = SimpleNamespace(get_token=AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        inputs.update(http_client=client, identity=identity)
        result = bind_handover_semantics(**inputs)
        reader = result.semantic_compiler.sources.envelopes
        assert reader.local_root is None
        assert reader.identity is identity and reader.http_client is client
        identity.get_token.assert_not_called()
    assert not requests


def test_binding_revision_changes_semantic_attempt_identity(tmp_path):
    inputs = arguments(tmp_path)
    before = bind_handover_semantics(**inputs)
    inputs["ontology_release"] = SimpleNamespace(digest="sha256:" + "b" * 64)
    after = bind_handover_semantics(**inputs)
    assert before.semantic_compiler.verifier.compiler_digest != (
        after.semantic_compiler.verifier.compiler_digest
    )
