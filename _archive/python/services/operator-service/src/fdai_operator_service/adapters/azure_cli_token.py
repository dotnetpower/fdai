"""Bounded Azure CLI token acquisition for local Operator Service adapters."""

from __future__ import annotations

import asyncio
import shutil

from fdai_operator_service.families.conversation.contracts import ConversationBoundaryError

AZURE_OPENAI_AUDIENCE = "https://cognitiveservices.azure.com/"
AZURE_CLI_TOKEN_TIMEOUT_SECONDS = 30.0
AZURE_CLI_KILL_WAIT_SECONDS = 5.0


async def azure_cli_token(audience: str) -> str:
    """Return one short-lived token or a redacted bounded availability error."""

    if shutil.which("az") is None:
        raise ConversationBoundaryError(503, "azure_cli_unavailable", "Azure CLI is unavailable")
    try:
        process = await asyncio.create_subprocess_exec(
            "az",
            "account",
            "get-access-token",
            "--resource",
            audience,
            "--query",
            "accessToken",
            "-o",
            "tsv",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise ConversationBoundaryError(
            503,
            "azure_cli_unavailable",
            "Azure CLI is unavailable",
        ) from exc
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=AZURE_CLI_TOKEN_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=AZURE_CLI_KILL_WAIT_SECONDS)
        except TimeoutError:
            pass
        raise ConversationBoundaryError(
            503,
            "azure_cli_token_timeout",
            "Azure CLI token acquisition timed out",
        ) from exc
    token = stdout.decode().strip()
    if process.returncode != 0 or not token:
        raise ConversationBoundaryError(
            503,
            "azure_cli_token_unavailable",
            "Azure CLI token is unavailable",
        )
    return token


__all__ = [
    "AZURE_CLI_KILL_WAIT_SECONDS",
    "AZURE_CLI_TOKEN_TIMEOUT_SECONDS",
    "AZURE_OPENAI_AUDIENCE",
    "azure_cli_token",
]
