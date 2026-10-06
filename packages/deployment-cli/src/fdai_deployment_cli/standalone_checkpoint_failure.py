"""Bounded failure summaries for standalone managed-host checkpoints."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

_ARM_RESOURCE_ID = re.compile(r"/subscriptions/[^\s\"']+", re.IGNORECASE)
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(token|secret|password|key|connection[_ -]?string)\b\s*[:=]\s*\S+"
)
_HOSTNAME = re.compile(
    r"\b(?=[A-Za-z0-9.-]{5,253}\b)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}"
    r"[A-Za-z0-9])?\.)+(?:[A-Za-z]{2,63})\b"
)
_PROVIDER_ERROR_CODE = re.compile(
    r"\b(?:OverconstrainedZonalAllocationRequest|AllocationFailed|ParameterOutOfRange|"
    r"[A-Z][A-Za-z0-9]*(?:Failed|Failure|Denied|Error|NotFound|OutOfRange|Request))\b"
)
_FAILURE_EXCERPT_LIMIT = 700


class ManagedHostCheckpointError(ValueError):
    """A checkpoint failure that can be returned to the workstation safely."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        provider_error_codes: tuple[str, ...] = (),
        excerpt: str = "",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.provider_error_codes = provider_error_codes
        self.excerpt = excerpt


def failure_record(exc: BaseException) -> dict[str, object]:
    if isinstance(exc, ManagedHostCheckpointError):
        reason_code = exc.reason_code
        provider_error_codes = list(exc.provider_error_codes)
        excerpt = exc.excerpt or sanitize_failure_text(str(exc))
    else:
        reason_code = "managed_host_checkpoint_failed"
        provider_error_codes = provider_error_codes_from_text(str(exc))
        excerpt = sanitize_failure_text(str(exc))
    return {
        "schema_version": "fdai.standalone-host-failure.v1",
        "state": "failed",
        "reason_code": reason_code,
        "provider_error_codes": provider_error_codes,
        "message_excerpt": excerpt,
        "mutation_performed": False,
        "subscription_ready": False,
    }


def remote_failure(result: subprocess.CompletedProcess[object]) -> dict[str, Any] | None:
    for stream in (getattr(result, "stderr", ""), getattr(result, "stdout", "")):
        text = (
            stream.decode("utf-8", errors="replace") if isinstance(stream, bytes) else str(stream)
        )
        for line in reversed(text.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(value, dict)
                and value.get("schema_version") == "fdai.standalone-host-failure.v1"
                and isinstance(value.get("reason_code"), str)
                and isinstance(value.get("message_excerpt"), str)
            ):
                return value
    return None


def terraform_failure(reason: str, result: subprocess.CompletedProcess[Any]) -> ValueError:
    output = "\n".join(
        _output_part(part)
        for part in (getattr(result, "stdout", ""), getattr(result, "stderr", ""))
        if part not in (None, b"", "")
    )
    codes = tuple(provider_error_codes_from_text(output))
    if codes:
        # Terraform prints progress before diagnostics; the bounded excerpt must keep the error.
        first_error = output.find("Error: ")
        excerpt = sanitize_failure_text(output[first_error:] if first_error >= 0 else output)
        return ManagedHostCheckpointError(
            "terraform_provider_error",
            f"{reason}; provider_error_code={','.join(codes)}; excerpt={excerpt}",
            provider_error_codes=codes,
            excerpt=excerpt,
        )
    return ValueError(reason)


def sanitize_failure_text(value: object) -> str:
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    text = _ARM_RESOURCE_ID.sub("<redacted-resource-id>", text)
    text = _GUID.sub("<redacted-guid>", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=<redacted-secret>", text)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted-token>", text)
    text = _HOSTNAME.sub("<redacted-hostname>", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _FAILURE_EXCERPT_LIMIT:
        return text[: _FAILURE_EXCERPT_LIMIT - 3].rstrip() + "..."
    return text


def provider_error_codes_from_text(value: object) -> list[str]:
    codes: list[str] = []
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    for match in _PROVIDER_ERROR_CODE.finditer(text):
        code = match.group(0)
        if code not in codes:
            codes.append(code)
    return codes[:5]


def _output_part(value: object) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
