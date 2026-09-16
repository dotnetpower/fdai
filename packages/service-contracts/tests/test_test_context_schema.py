"""Public test-context schema registration preserves the typed wire boundary."""

import json
import runpy
from copy import deepcopy
from pathlib import Path

import pytest

from fdai_service_contracts import (
    TEST_CONTEXT_RESULT_TOPIC,
    ContractValidationError,
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)
from fdai_service_contracts import (
    TestContextApplication as ContextApplication,
)
from fdai_service_contracts import (
    TestContextCommand as ContextCommand,
)
from fdai_service_contracts import (
    TestContextDraft as ContextDraft,
)
from fdai_service_contracts import (
    TestContextRequest as ContextRequest,
)
from fdai_service_contracts import (
    TestContextWindow as ContextWindow,
)
from fdai_service_contracts.ontology_query import content_digest


def _command() -> dict:
    return {
        "schema_version": "1.0.0",
        "request": {
            "operation": "propose",
            "context_id": "example-context",
            "access_scope_digest": "a" * 64,
            "target_ref": "example-resource",
            "signal_code": "example-signal",
            "expected_revision": 0,
            "policy_revision": "policy-v1",
            "source_ref": "example-source",
            "semantic_receipt": "sha256:" + "b" * 64,
            "expected_min": 10.0,
            "expected_max": 20.0,
            "effective_from": "2026-09-15T10:00:00Z",
            "effective_to": "2026-09-15T11:00:00Z",
        },
        "actor_id": "example-requester",
        "actor_roles": ["Contributor"],
        "idempotency_key": "example-command",
        "requested_at": "2026-09-15T09:00:00Z",
        "execution_authority": False,
    }


@pytest.mark.parametrize(
    "name",
    ["test-context-draft", "test-context-command", "test-context-application"],
)
def test_test_context_schemas_are_available_from_the_public_registry(name: str) -> None:
    registry = PackageResourceSchemaRegistry()
    schema = registry.get(name, "1.0.0")
    assert schema["additionalProperties"] is False
    assert name in registry.names()


def test_registered_context_schemas_preserve_typed_roundtrips() -> None:
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    command = ContextCommand.model_validate(_command())
    request = ContextRequest.model_validate(_command()["request"])
    window = ContextWindow(
        expected_min=request.expected_min,
        expected_max=request.expected_max,
        effective_from=request.effective_from,
        effective_to=request.effective_to,
    )
    draft = ContextDraft(
        target_ref=request.target_ref,
        signal_code=request.signal_code,
        window=window,
        source_ref=request.source_ref,
        semantic_receipt=request.semantic_receipt,
    )
    application = ContextApplication(
        command_digest=content_digest(command.model_dump(mode="json")),
        actor_id=command.actor_id,
        request_key=command.idempotency_key,
        context_id=request.context_id,
        access_scope_digest=request.access_scope_digest,
        target_ref=request.target_ref,
        policy_revision=request.policy_revision,
        revision=1,
        state="proposed",
        context_digest="sha256:" + "c" * 64,
    )
    assert application.matches(command)
    assert TEST_CONTEXT_RESULT_TOPIC == "core.test-context.projections"
    for name, model in (
        ("test-context-command", command),
        ("test-context-draft", draft),
        ("test-context-application", application),
    ):
        payload = json.loads(model.model_dump_json())
        validator.validate(name, payload, version="1.0.0")
        assert type(model).model_validate(payload) == model
        for invalid in ({**payload, "execution_authority": True}, {**payload, "extra": True}):
            with pytest.raises(ContractValidationError):
                validator.validate(name, invalid, version="1.0.0")


@pytest.mark.parametrize(
    "location,value",
    [
        (("request", "expected_min"), 21.0),
        (("request", "expected_revision"), 1),
        (("request", "expected_revision"), True),
        (("request", "effective_to"), "2026-09-15T09:00:00Z"),
        (("request", "effective_to"), "2026-09-15T11:00:00"),
        (("request", "expected_max"), None),
        (("request", "access_scope_digest"), "invalid-scope"),
        (("actor_roles",), []),
        (("actor_roles",), ["Owner", "Owner"]),
        (("requested_at",), "2026-09-15T09:00:00"),
    ],
)
def test_registry_rejects_structural_and_semantic_command_defects(location, value) -> None:
    payload = deepcopy(_command())
    target = payload
    for part in location[:-1]:
        target = target[part]
    target[location[-1]] = value
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    with pytest.raises(ContractValidationError):
        validator.validate("test-context-command", payload, version="1.0.0")


def test_review_schema_cannot_bypass_typed_role_or_envelope_validation() -> None:
    payload = _command()
    payload["request"].update(operation="review", expected_revision=1)
    for field in ("expected_min", "expected_max", "effective_from", "effective_to"):
        del payload["request"][field]
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    with pytest.raises(ContractValidationError):
        validator.validate("test-context-command", payload)
    payload["actor_roles"] = ["Approver"]
    validator.validate("test-context-command", payload)
    payload["request"]["expected_min"] = 12.0
    with pytest.raises(ContractValidationError):
        validator.validate("test-context-command", payload)


def test_context_schema_generation_matches_shipped_files() -> None:
    root = Path(__file__).resolve().parents[3]
    generator = runpy.run_path(
        str(root / "scripts/quality/contracts/generate_test_context_schemas.py")
    )
    rendered = generator["render_schemas"]()
    assert rendered == generator["render_schemas"]()
    for name, content in rendered.items():
        path = root / "packages/service-contracts/src/fdai_service_contracts/schemas" / name
        assert (path / "1.0.0.json").read_text(encoding="utf-8") == content
