#!/usr/bin/env python3
"""Store controller credentials without Terraform, argv values, files or secret readback.

The fine-grained PAT needs repository Administration: read/write and Actions: read.
Webhooks: read/write is optional, only when controller-managed webhook setup is used.
The operator supplies the PAT directly at the hidden terminal prompt. Supply an
independently configured webhook key with --prompt-webhook-key, or generate one in
memory with --generate-webhook-key. Generation never prints a key for copying.
--disable-webhook explicitly stores the unavailable placeholder for polling-only use.
This only stores secrets; a controller revision restart and live verification are
separate operator actions. Never fetch a credential from an existing worker.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import warnings
from typing import IO, Any

APP_ID = re.compile(
    r"/subscriptions/(?P<subscription>[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}"
    r"-[0-9a-fA-F]{12})/resourceGroups/[A-Za-z0-9_().-]+"
    r"/providers/Microsoft\.App/containerApps/ca-[a-z0-9-]+-controller",
    re.IGNORECASE,
)


class CredentialError(Exception):
    """Sanitized operator failure; never retain an HTTP response or provider body."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        raise CredentialError("redirect_refused")


def hidden_value(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        value = getpass.getpass(prompt)
    if (
        not value
        or value == "unset"
        or len(value) > 4096
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        raise CredentialError("invalid_credential")
    return value


def access_token(subscription: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", subscription):
        raise CredentialError("invalid_subscription")
    azure_cli = shutil.which("az")
    if azure_cli is None:
        raise CredentialError("azure_identity_unavailable")
    try:
        result = subprocess.run(  # noqa: S603 - Fixed CLI verb and validated UUID, without a shell.
            [
                azure_cli,
                "account",
                "get-access-token",
                "--subscription",
                subscription,
                "--resource",
                "https://management.azure.com/",
                "--query",
                "accessToken",
                "--output",
                "tsv",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        raise CredentialError("azure_identity_unavailable") from None
    if result.returncode:
        raise CredentialError("azure_identity_unavailable")
    try:
        token = result.stdout.decode("ascii").strip()
    except UnicodeError:
        raise CredentialError("azure_identity_unavailable") from None
    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise CredentialError("azure_identity_unavailable")
    return token


def store_credentials(resource_id: str, token: str, pat: str, webhook_key: str) -> None:
    """PATCH only the validated controller app; never list or read provider secrets."""
    if not APP_ID.fullmatch(resource_id):
        raise CredentialError("invalid_controller_resource_id")
    body = json.dumps(
        {
            "properties": {
                "configuration": {
                    "secrets": [
                        {"name": "github-pat", "value": pat},
                        {"name": "webhook-hmac", "value": webhook_key},
                    ]
                }
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://management.azure.com" + resource_id + "?api-version=2024-03-01",
        data=body,
        method="PATCH",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    # Direct TLS only: a redirect or environment proxy must not receive the PAT.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            status = response.status
        if status == 200:
            return
        if status != 202:
            raise CredentialError("credential_update_unconfirmed")
        for _ in range(30):
            check = urllib.request.Request(
                "https://management.azure.com" + resource_id + "?api-version=2024-03-01",
                method="GET",
                headers={"Authorization": request.get_header("Authorization") or ""},
            )
            with opener.open(check, timeout=30) as poll:
                if poll.status != 200 or not hasattr(poll, "read"):
                    raise CredentialError("credential_update_unconfirmed")
                raw = json.loads(poll.read(1024 * 1024).decode("utf-8"))
            state = (
                raw.get("properties", {}).get("provisioningState")
                if isinstance(raw, dict)
                else None
            )
            if state == "Succeeded":
                return
            if state in {"Failed", "Canceled"}:
                raise CredentialError("credential_update_unconfirmed")
            time.sleep(2)
        raise CredentialError("credential_update_unconfirmed")
    except (urllib.error.URLError, OSError, ValueError):
        raise CredentialError("credential_update_failed") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-resource-id", required=True)
    webhook = parser.add_mutually_exclusive_group(required=True)
    webhook.add_argument("--prompt-webhook-key", action="store_true")
    webhook.add_argument("--generate-webhook-key", action="store_true")
    webhook.add_argument("--disable-webhook", action="store_true")
    args = parser.parse_args(argv)
    match = APP_ID.fullmatch(args.controller_resource_id)
    if match is None:
        parser.error("Use the controller_resource_id Terraform output, never a worker Job.")
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print("credential_update_failed: interactive_terminal_required", file=sys.stderr)
        return 1
    try:
        token = access_token(match["subscription"])
        pat = hidden_value("Controller GitHub PAT (hidden): ")
        if args.disable_webhook:
            webhook_key = "unset"
        elif args.prompt_webhook_key:
            webhook_key = hidden_value("Controller webhook HMAC key (hidden): ")
        else:
            webhook_key = secrets.token_urlsafe(48)
        if not args.disable_webhook and len(webhook_key) < 32:
            raise CredentialError("invalid_webhook_key")
        store_credentials(args.controller_resource_id, token, pat, webhook_key)
    except (CredentialError, getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        print("credential_update_failed", file=sys.stderr)
        return 1
    print("controller_credentials_stored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
