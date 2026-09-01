"""Key Vault persistence tests for the Teams Workflows endpoint."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest
from fdai_operator_service.environment import OperatorServiceConfigurationError
from fdai_operator_service.iam_composition import build_teams_workflow_binding_store
from fdai_operator_service.teams_workflow_binding import (
    KEY_VAULT_SCOPE,
    KeyVaultTeamsWorkflowBindingStore,
    LocalEncryptedTeamsWorkflowBindingStore,
    TeamsWorkflowBindingConfig,
    TeamsWorkflowBindingError,
)

URL = (
    "https://example.e4.environment.api.powerplatform.com/"
    "powerautomate/automations/direct/workflows/"
    "d74f3e0ee1314a4191c650cfda483a70/triggers/manual/paths/invoke"
    "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
    "&sig=abcdefghijklmnopqrstuvwxyz012345"
)
VAULT = "https://example.vault.azure.net"
VERSION = "0123456789abcdef0123456789abcdef"


class RecordingHttpClient:
    def __init__(self) -> None:
        self.put_json: object = None
        self.get_url: str | None = None

    async def put(self, url: str, **kwargs: object) -> httpx.Response:
        self.put_json = kwargs["json"]
        request = httpx.Request("PUT", url)
        return httpx.Response(
            200,
            request=request,
            json={"id": f"{VAULT}/secrets/fdai-teams-workflow-endpoint/{VERSION}"},
        )

    async def get(self, url: str, **_: object) -> httpx.Response:
        self.get_url = url
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"value": URL},
        )


async def test_writes_and_verifies_one_exact_secret_version() -> None:
    scopes: list[str] = []
    client = RecordingHttpClient()

    async def token_provider(scope: str) -> str:
        scopes.append(scope)
        return "token"

    store = KeyVaultTeamsWorkflowBindingStore(
        config=TeamsWorkflowBindingConfig(
            vault_url=VAULT,
            secret_name="fdai-teams-workflow-endpoint",
        ),
        token_provider=token_provider,
        http_client=client,
    )

    saved = await store.save_and_verify(webhook_url=URL, request_id="save-1")

    assert scopes == [KEY_VAULT_SCOPE]
    assert saved.webhook_url == URL
    assert saved.version == VERSION
    assert len(saved.endpoint_digest) == 64
    assert client.put_json == {
        "value": URL,
        "tags": {
            "fdai-purpose": "teams-workflow-binding",
            "fdai-request-id": "save-1",
        },
    }
    assert client.get_url == (
        f"{VAULT}/secrets/fdai-teams-workflow-endpoint/{VERSION}?api-version=7.4"
    )


async def test_rejects_a_verification_value_that_differs_from_the_save() -> None:
    class MismatchedClient(RecordingHttpClient):
        async def get(self, url: str, **_: object) -> httpx.Response:
            return httpx.Response(
                200,
                request=httpx.Request("GET", url),
                json={"value": f"{URL}changed"},
            )

    async def token_provider(_: str) -> str:
        return "token"

    store = KeyVaultTeamsWorkflowBindingStore(
        config=TeamsWorkflowBindingConfig(
            vault_url=VAULT,
            secret_name="fdai-teams-workflow-endpoint",
        ),
        token_provider=token_provider,
        http_client=MismatchedClient(),
    )

    with pytest.raises(TeamsWorkflowBindingError, match="did not match"):
        await store.save_and_verify(webhook_url=URL, request_id="save-1")


@pytest.mark.parametrize(
    ("vault_url", "secret_name"),
    [
        ("http://example.vault.azure.net", "fdai-teams-workflow-endpoint"),
        ("https://example.invalid", "fdai-teams-workflow-endpoint"),
        (VAULT, "invalid/name"),
    ],
)
def test_rejects_invalid_binding_targets(vault_url: str, secret_name: str) -> None:
    with pytest.raises(ValueError):
        TeamsWorkflowBindingConfig(vault_url=vault_url, secret_name=secret_name)


def test_composition_requires_the_complete_secret_target() -> None:
    class Environment:
        values = {
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_TEAMS_WORKFLOW_KEY_VAULT_URL": VAULT,
        }

    with pytest.raises(OperatorServiceConfigurationError, match="configured together"):
        build_teams_workflow_binding_store(Environment(), object())  # type: ignore[arg-type]


def test_composition_stays_unavailable_without_a_secret_target() -> None:
    class Environment:
        values = {"FDAI_EXECUTION_VENUE": "deployed"}

    assert (
        build_teams_workflow_binding_store(  # type: ignore[arg-type]
            Environment(),
            object(),  # type: ignore[arg-type]
        )
        is None
    )


async def test_local_store_persists_ciphertext_and_verifies_plaintext() -> None:
    class StateStore:
        value: dict[str, object] | None = None

        async def write_state(self, _: str, value: Mapping[str, object]) -> None:
            self.value = dict(value)

        async def read_state(self, _: str) -> dict[str, object] | None:
            return None if self.value is None else dict(self.value)

    state = StateStore()
    store = LocalEncryptedTeamsWorkflowBindingStore(
        store=state,
        key_material="postgresql://operator:secret@127.0.0.1/fdai",
    )

    saved = await store.save_and_verify(webhook_url=URL, request_id="save-1")

    assert saved.webhook_url == URL
    assert state.value is not None
    assert URL not in repr(state.value)
    assert isinstance(state.value["ciphertext"], str)
