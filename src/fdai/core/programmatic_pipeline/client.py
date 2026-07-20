"""Generate the narrow trusted client module mounted into an isolated child."""

from __future__ import annotations

import hashlib
import json

from fdai.shared.providers.programmatic_pipeline import GeneratedPipelineClientContract


def generate_pipeline_client(
    allowed_tools: frozenset[str],
) -> GeneratedPipelineClientContract:
    tools_json = json.dumps(sorted(allowed_tools), separators=(",", ":"))
    source = _CLIENT_TEMPLATE.replace("__ALLOWED_TOOLS__", tools_json)
    return GeneratedPipelineClientContract(
        module_name="fdai_pipeline_client",
        class_name="PipelineClient",
        allowed_tools=tuple(sorted(allowed_tools)),
        source=source,
        source_digest=hashlib.sha256(source.encode("utf-8")).hexdigest(),
    )


_CLIENT_TEMPLATE = """from __future__ import annotations

import json
import os
import socket

_ALLOWED_TOOLS = frozenset(__ALLOWED_TOOLS__)


class PipelineClientError(RuntimeError):
    pass


class PipelineClient:
    def __init__(self) -> None:
        self._run_id = os.environ["FDAI_PIPELINE_RUN_ID"]
        self._token = os.environ["FDAI_PIPELINE_CAPABILITY_TOKEN"]
        self._socket_path = os.environ["FDAI_PIPELINE_BROKER_SOCKET"]
        self._timeout = float(os.environ["FDAI_PIPELINE_CALL_TIMEOUT"])
        self._sequence = 0

    def call(self, tool_id: str, arguments: dict[str, object]) -> object:
        if tool_id not in _ALLOWED_TOOLS:
            raise PipelineClientError("tool is outside the generated client allowlist")
        self._sequence += 1
        request = {
            "run_id": self._run_id,
            "capability_token": self._token,
            "call_id": f"call-{self._sequence}",
            "tool_id": tool_id,
            "arguments_json": json.dumps(arguments, separators=(",", ":"), sort_keys=True),
        }
        payload = json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\\n"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self._timeout)
            client.connect(self._socket_path)
            client.sendall(payload)
            response_bytes = bytearray()
            while not response_bytes.endswith(b"\\n"):
                chunk = client.recv(8192)
                if not chunk:
                    break
                response_bytes.extend(chunk)
        response = json.loads(response_bytes)
        if not response.get("ok"):
            raise PipelineClientError(str(response.get("error_code") or "broker_failure"))
        return json.loads(response["output_json"])
"""


__all__ = ["generate_pipeline_client"]
