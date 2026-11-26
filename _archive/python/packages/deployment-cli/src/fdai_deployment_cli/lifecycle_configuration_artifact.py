"""The existing local configuration container, without trust or filesystem decisions."""

from __future__ import annotations

import base64

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_configuration_package import SignedConfigurationPackage
from fdai_deployment_cli.lifecycle_configuration_sealing import read_object

CONFIGURATION_FILE_FORMAT = "fdai.lifecycle-configuration-file.v1"
MAX_CONFIGURATION_ARTIFACT_BYTES = 2 * 1024 * 1024


def configuration_artifact_bytes(package: SignedConfigurationPackage) -> bytes:
    return canonical_bytes(
        {
            "format": CONFIGURATION_FILE_FORMAT,
            "payload": base64.b64encode(package.payload).decode("ascii"),
            "signature": base64.b64encode(package.signature).decode("ascii"),
        }
    )


def read_configuration_artifact(content: bytes) -> SignedConfigurationPackage:
    if len(content) > MAX_CONFIGURATION_ARTIFACT_BYTES:
        raise ValueError("configuration artifact exceeds its byte bound")
    document = read_object(content)
    if set(document) != {"format", "payload", "signature"}:
        raise ValueError("configuration input fields are invalid")
    if document["format"] != CONFIGURATION_FILE_FORMAT:
        raise ValueError("unsupported configuration artifact format")
    payload_text, signature_text = document["payload"], document["signature"]
    if (
        not isinstance(payload_text, str)
        or not payload_text
        or not isinstance(signature_text, str)
        or not signature_text
    ):
        raise ValueError("configuration field must be nonempty text")
    payload = base64.b64decode(payload_text, validate=True)
    signature = base64.b64decode(signature_text, validate=True)
    if len(payload) > 1024 * 1024 or len(signature) != 64:
        raise ValueError("configuration artifact payload or signature size is invalid")
    return SignedConfigurationPackage(payload, signature)
