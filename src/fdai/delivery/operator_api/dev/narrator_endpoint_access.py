"""Local-dev convenience: auto-open the Azure OpenAI account behind the
narrator so the CommandDeck LLM path is reachable right after the read
API starts, instead of silently falling back to the deterministic
answerer.

Why this exists
---------------
The dev narrator points at an Azure OpenAI account (for example
``oai-fdai-dev-krc.openai.azure.com``). A tenant policy can flip that
account to ``publicNetworkAccess: Disabled``, after which every keyless
call from a laptop returns ``403 "Public access is disabled"``. The
:class:`LatencyRoutedChatBackend` warm-up then times out, ``/chat/health``
reports ``azure-ad-routed-unavailable``, and the console shows a
``deterministic`` badge with no obvious cause.

This module runs a best-effort ``az`` reconciliation at Operator API startup:
it finds the account, and - only when the endpoint is not reachable -
adds the machine's current public IP to the account firewall and enables
restricted public access (``defaultAction: Deny`` + the single IP). An
already-open account is left untouched.

Contract
--------
- **On by default (local dev).** Runs whenever the local dev Operator API boots,
  unless explicitly disabled with ``FDAI_NARRATOR_AUTO_OPEN_AOAI=0`` (also
  accepts ``false`` / ``no`` / ``off``).
- **Fail-safe.** Every failure path (no ``az`` CLI, not logged in, RBAC
  denied, endpoint unresolvable, timeout, malformed output) is logged at
  WARNING and swallowed, so the Operator API still boots and the console
  keeps working via the deterministic fallback.
- **Least privilege on the resource.** It never sets a fully open
  firewall: it restricts to the current IP with ``defaultAction: Deny``.
- **Dev-only.** It shells out to ``az`` against the developer's own
  signed-in subscription. It MUST NOT be wired into a production build;
  the only caller is the dev/local factory, which already asserts
  dev/local-CLI mode at import.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from urllib.parse import urlsplit
from urllib.request import urlopen

AUTO_OPEN_ENV = "FDAI_NARRATOR_AUTO_OPEN_AOAI"
_AUTO_OPEN_DISABLE_VALUES = frozenset({"0", "false", "no", "off"})

_AOAI_HOST_SUFFIXES = (".openai.azure.com", ".cognitiveservices.azure.com")
# Fixed, well-known plaintext-IP echo services. Ordered by preference; the
# first that answers within the timeout wins.
_IP_ECHO_SERVICES = (
    "https://ifconfig.me/ip",
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
)
_IP_TIMEOUT_SECONDS = 6
_AZ_TIMEOUT_SECONDS = 40

_LOGGER = logging.getLogger(__name__)


def auto_open_enabled(env: dict[str, str] | None = None) -> bool:
    """Return whether the startup auto-open runs. On by default; disabled only
    when ``FDAI_NARRATOR_AUTO_OPEN_AOAI`` is an explicit falsy value."""
    src = env if env is not None else os.environ
    raw = src.get(AUTO_OPEN_ENV, "").strip().lower()
    return raw not in _AUTO_OPEN_DISABLE_VALUES


def _endpoint_hosts(backend: object) -> list[str]:
    """Best-effort extraction of Azure OpenAI hostnames from a chat backend.

    Handles both the routed backend (``endpoints()`` -> list of URLs) and a
    single :class:`AzureAdChatBackend` (``_endpoint`` attribute). Anything
    else yields an empty list, which callers treat as "nothing to open".
    """
    urls: list[str] = []
    endpoints = getattr(backend, "endpoints", None)
    if callable(endpoints):
        try:
            got = endpoints()
        except Exception:  # noqa: BLE001 - introspection only, never fatal
            got = None
        if isinstance(got, (list, tuple)):
            urls.extend(str(item) for item in got)
    single = getattr(backend, "_endpoint", None)
    if isinstance(single, str):
        urls.append(single)
    hosts: list[str] = []
    for url in urls:
        candidate = url if "://" in url else f"https://{url}"
        host = urlsplit(candidate).hostname
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def _account_name_from_host(host: str) -> str | None:
    """Return the Cognitive Services account name (subdomain) or ``None``."""
    low = host.lower()
    for suffix in _AOAI_HOST_SUFFIXES:
        if low.endswith(suffix):
            label = low[: -len(suffix)]
            return label or None
    return None


def _current_public_ip(logger: logging.Logger) -> str | None:
    """Resolve this machine's public egress IP, or ``None`` on failure."""
    for service in _IP_ECHO_SERVICES:
        try:
            with urlopen(service, timeout=_IP_TIMEOUT_SECONDS) as resp:  # noqa: S310 - fixed https hosts
                payload = resp.read()
        except Exception:  # noqa: BLE001,S112 - try the next echo service
            continue
        if not isinstance(payload, bytes):
            continue
        ip = payload.decode("utf-8").strip()
        if ip:
            return ip
    logger.warning("narrator auto-open: could not determine public IP; skipping")
    return None


def _az_json(args: list[str], logger: logging.Logger) -> object | None:
    """Run ``az <args> -o json`` and parse stdout, or ``None`` on any failure."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed 'az' invocation, dev-only
            ["az", *args, "-o", "json"],  # noqa: S607 - 'az' resolved from PATH, dev-only
            capture_output=True,
            text=True,
            timeout=_AZ_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("narrator auto-open: 'az' CLI not found on PATH; skipping")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("narrator auto-open: 'az %s' timed out", " ".join(args))
        return None
    if proc.returncode != 0:
        logger.warning(
            "narrator auto-open: 'az %s' failed (rc=%s): %s",
            " ".join(args),
            proc.returncode,
            (proc.stderr or "").strip()[:300],
        )
        return None
    try:
        parsed: object = json.loads(proc.stdout or "null")
        return parsed
    except json.JSONDecodeError:
        logger.warning("narrator auto-open: 'az %s' returned non-JSON output", " ".join(args))
        return None


def _ensure_account_open(account: str, logger: logging.Logger) -> None:
    """Reconcile one Azure OpenAI account so the current IP can reach it.

    No-op when the account is already reachable (public access enabled and
    either no deny-list or the current IP already allowed).
    """
    listing = _az_json(
        [
            "resource",
            "list",
            "--resource-type",
            "Microsoft.CognitiveServices/accounts",
            "--name",
            account,
        ],
        logger,
    )
    if not isinstance(listing, list) or not listing:
        logger.warning(
            "narrator auto-open: account %r not found in the current subscription; "
            "check 'az account show' and the resolved-models endpoint",
            account,
        )
        return
    entry = listing[0]
    resource_id = entry.get("id") if isinstance(entry, dict) else None
    resource_group = entry.get("resourceGroup") if isinstance(entry, dict) else None
    name = (entry.get("name") if isinstance(entry, dict) else None) or account
    if not resource_id or not resource_group:
        logger.warning("narrator auto-open: could not resolve id/resource-group for %r", account)
        return

    shown = _az_json(
        [
            "cognitiveservices",
            "account",
            "show",
            "--name",
            name,
            "--resource-group",
            resource_group,
        ],
        logger,
    )
    props = shown.get("properties", {}) if isinstance(shown, dict) else {}
    if not isinstance(props, dict):
        props = {}
    pna = str(props.get("publicNetworkAccess") or "")
    acls = props.get("networkAcls") if isinstance(props.get("networkAcls"), dict) else {}
    default_action = str((acls or {}).get("defaultAction") or "")
    ip_rules = {
        str(rule.get("value"))
        for rule in (acls or {}).get("ipRules", [])
        if isinstance(rule, dict) and rule.get("value")
    }

    ip = _current_public_ip(logger)
    pna_enabled = pna.lower() == "enabled"
    deny_default = default_action.lower() == "deny"
    already_reachable = pna_enabled and (not deny_default or (ip is not None and ip in ip_rules))
    if already_reachable:
        logger.info(
            "narrator auto-open: %s already reachable (publicNetworkAccess=%s, defaultAction=%s)",
            name,
            pna or "unset",
            default_action or "unset",
        )
        return
    if ip is None:
        # Cannot safely open a deny-listed / disabled endpoint without the IP.
        return

    if ip not in ip_rules:
        _az_json(
            [
                "cognitiveservices",
                "account",
                "network-rule",
                "add",
                "--name",
                name,
                "--resource-group",
                resource_group,
                "--ip-address",
                ip,
            ],
            logger,
        )
    updated = _az_json(
        [
            "resource",
            "update",
            "--ids",
            resource_id,
            "--set",
            "properties.publicNetworkAccess=Enabled",
            "properties.networkAcls.defaultAction=Deny",
        ],
        logger,
    )
    if updated is not None:
        logger.info(
            "narrator auto-open: enabled restricted public access on %s for ip %s",
            name,
            ip,
        )


async def ensure_narrator_endpoint_open(
    backend: object,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Startup hook: open the narrator's Azure OpenAI account for this machine.

    Gated behind ``FDAI_NARRATOR_AUTO_OPEN_AOAI=1``; a no-op otherwise. All
    blocking work (``az`` subprocess calls, the public-IP lookup) runs in a
    worker thread so the event loop is never blocked, and every failure is
    swallowed so a broken ``az`` environment cannot break Operator API startup.
    """
    log = logger or _LOGGER
    if not auto_open_enabled():
        return
    hosts = _endpoint_hosts(backend)
    accounts: list[str] = []
    for host in hosts:
        account = _account_name_from_host(host)
        if account and account not in accounts:
            accounts.append(account)
    if not accounts:
        log.info(
            "narrator auto-open: no Azure OpenAI endpoint on the wired backend; nothing to open"
        )
        return
    for account in accounts:
        try:
            await asyncio.to_thread(_ensure_account_open, account, log)
        except Exception as exc:  # noqa: BLE001 - fail-safe: never break startup
            log.warning("narrator auto-open: unexpected error for %s: %s", account, exc)
