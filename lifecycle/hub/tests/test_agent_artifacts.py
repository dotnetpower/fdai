from __future__ import annotations

import base64
import json

import pytest
from fdai_deployment_cli.contracts import canonical_digest

from fdai_lifecycle_hub.agent_artifacts import (
    _MAX_CONTAINER_BASE64_CHARACTERS,
    _configuration_artifact,
)


def _container(payload: bytes, *, signature: str | None = None) -> str:
    document = {
        "format": "fdai.lifecycle-configuration-file.v1",
        "payload": base64.b64encode(payload).decode("ascii"),
        "signature": signature or base64.b64encode(b"s" * 64).decode("ascii"),
    }
    return base64.b64encode(json.dumps(document).encode()).decode("ascii")


def test_configuration_artifact_accepts_one_strict_signed_payload():
    payload = b'{"revision":"one"}'

    assert _configuration_artifact(_container(payload), canonical_digest({"revision": "one"})) == (
        payload,
        b"s" * 64,
    )


@pytest.mark.parametrize(
    ("payload", "digest"),
    [
        (b'{"revision":"one","revision":"two"}', canonical_digest({"revision": "two"})),
        ('{"revision":"one"}'.encode("utf-16"), canonical_digest({"revision": "one"})),
        (b'{"value":NaN}', canonical_digest({"value": "not-a-number"})),
    ],
)
def test_configuration_artifact_rejects_ambiguous_payload_json(payload, digest):
    with pytest.raises(ValueError, match="payload is invalid"):
        _configuration_artifact(_container(payload), digest)


def test_configuration_artifact_rejects_ambiguous_container_json():
    payload = base64.b64encode(b'{"revision":"one"}').decode("ascii")
    signature = base64.b64encode(b"s" * 64).decode("ascii")
    duplicate = (
        '{"format":"fdai.lifecycle-configuration-file.v1",'
        f'"payload":"{payload}","payload":"{payload}","signature":"{signature}"'
        "}"
    )

    with pytest.raises(ValueError, match="container is invalid"):
        _configuration_artifact(
            base64.b64encode(duplicate.encode()).decode("ascii"),
            canonical_digest({"revision": "one"}),
        )


def test_configuration_artifact_rejects_encoded_fields_before_decode():
    payload = b'{"revision":"one"}'
    with pytest.raises(ValueError, match="container is invalid"):
        _configuration_artifact(
            _container(payload, signature="A" * 92),
            canonical_digest({"revision": "one"}),
        )
    with pytest.raises(ValueError, match="container is invalid"):
        _configuration_artifact(
            "A" * (_MAX_CONTAINER_BASE64_CHARACTERS + 1),
            canonical_digest({"revision": "one"}),
        )
