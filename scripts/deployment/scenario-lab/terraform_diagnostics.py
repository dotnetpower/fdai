#!/usr/bin/env python3
"""Project allowlisted tokens from a runner-local Terraform JSON UI log.

The scenario-lab workflow writes `terraform plan -json` and `terraform apply -json` output to a
runner-local log and prints only this projection when the command fails:

- the number of error diagnostics;
- categories matched in the summary and detail of error diagnostics;
- allowlisted resource addresses from error diagnostics and, for apply, `apply_errored` hooks;
- Azure error codes and HTTP statuses taken from the summary and detail of error diagnostics.

Refresh and progress messages, warnings, non-JSON output, raw text, identifiers, names, and values
never reach the output.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

STAGES = ("plan", "apply")
_INDEX_KEY = r"(?:\[(?:[0-9]+|\"[A-Za-z0-9_.:-]+\")\])?"
ADDRESS = re.compile(
    r"(?:module\.[A-Za-z0-9_-]+" + _INDEX_KEY + r"\.)*"
    r"(?:data\.)?(?:azurerm|random|terraform)_[A-Za-z0-9_]+\.[A-Za-z0-9_-]+" + _INDEX_KEY
)
_IDENTIFIER = r"([A-Za-z][A-Za-z0-9_.-]{1,127})"
CODE_PATTERNS = (
    re.compile(r'\bCode[=:]\s*"?' + _IDENTIFIER),
    re.compile(r'"code"\s*:\s*"' + _IDENTIFIER + '"'),
    re.compile(r'\b(?i:error[ _]?code)[=:]\s*"?' + _IDENTIFIER),
    re.compile(r"\bwith error:\s*([A-Z][A-Za-z0-9]{1,127}):"),
)
KNOWN_CODES = re.compile(
    r"\b(AnotherOperationInProgress|AuthorizationFailed|ExpiredAuthenticationToken"
    r"|InvalidAuthenticationToken|InvalidAuthenticationTokenTenant|LinkedAuthorizationFailed"
    r"|MissingSubscriptionRegistration|OperationNotAllowed|ParentResourceNotFound"
    r"|PrincipalNotFound|RequestDisallowedByPolicy|ResourceGroupNotFound|ResourceNotFound"
    r"|RetryableError|ScopeLocked|SubscriptionNotRegistered|TooManyRequests)\b"
)
STATUS_PATTERNS = (
    re.compile(r'\bStatus(?:Code)?[=:]\s*"?([1-5][0-9]{2})\b'),
    re.compile(r"\bunexpected status\s+([1-5][0-9]{2})\b"),
    re.compile(r"\bRESPONSE\s+([1-5][0-9]{2})\b"),
    re.compile(r"\b(?i:http status|status code)[: =]*([1-5][0-9]{2})\b"),
)
CATEGORY_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "authentication": re.compile(
        r"\b(?:authenticat(?:e|ed|ing|ion)|access token|managed ?identity(?:credential)?"
        r"|msi|imds|metadata endpoint|aadsts[0-9]+)\b",
        re.IGNORECASE,
    ),
    "authorization": re.compile(r"\bauthoriz(?:ation|ed)\b", re.IGNORECASE),
    "backend_state": re.compile(
        r"\b(?:error (?:loading|reading|refreshing|writing|saving) (?:the )?state"
        r"|failed to (?:load|read|persist|save|write) (?:the )?state"
        r"|failed to get existing workspaces|error loading backend"
        r"|failed to configure the backend|backend initialization required"
        r"|backend configuration changed)\b",
        re.IGNORECASE,
    ),
    "capacity_or_quota": re.compile(r"\b(?:capacity|quota)\b", re.IGNORECASE),
    "condition_failed": re.compile(r"\b(?:pre|post)condition failed\b", re.IGNORECASE),
    "conflict": re.compile(
        r"\b(?:anotheroperationinprogress|409 conflict|conflicting operation"
        r"|operation (?:is )?(?:already )?in progress|retryableerror)\b",
        re.IGNORECASE,
    ),
    "invalid_configuration_value": re.compile(
        r"\b(?:invalid (?:attribute name|index|expression|for_each argument"
        r"|count argument|template interpolation value|value for module argument"
        r"|combination of arguments|resource type)|incorrect attribute value type"
        r"|inconsistent conditional result types|missing resource instance key"
        r"|error in function call|conflicting configuration arguments)\b",
        re.IGNORECASE,
    ),
    "invalid_function_argument": re.compile(r"\binvalid function argument\b", re.IGNORECASE),
    "invalid_input_variable": re.compile(
        r"\binvalid value for (?:input )?variable\b", re.IGNORECASE
    ),
    "missing_input_variable": re.compile(r"\bno value for required variable\b", re.IGNORECASE),
    "missing_required_argument": re.compile(r"\bmissing required argument\b", re.IGNORECASE),
    "network": re.compile(
        r"\b(?:dial tcp|no such host|connection refused|connection reset"
        r"|network is unreachable|tls handshake|proxyconnect|i/o timeout)\b",
        re.IGNORECASE,
    ),
    "plugin_failure": re.compile(
        r"\b(?:plugin (?:did not respond|crashed|exited|error)|request cancelled)\b",
        re.IGNORECASE,
    ),
    "provider_configuration": re.compile(
        r"\b(?:invalid provider configuration|provider configuration not present"
        r"|missing required provider|building azurerm client|building account"
        r"|(?:unable to )?build(?:ing)? (?:an? )?authorizer"
        r"|could not configure [a-z]+ authorizer)\b",
        re.IGNORECASE,
    ),
    "provider_inconsistency": re.compile(
        r"\b(?:provider produced (?:inconsistent|invalid)|provider returned invalid)\b",
        re.IGNORECASE,
    ),
    "provider_installation": re.compile(
        r"\b(?:failed to (?:query available provider packages|install providers?"
        r"|instantiate provider|load plugin schemas|obtain provider schema)"
        r"|incompatible provider version|inconsistent dependency lock file"
        r"|required plugins are not installed|could not load plugin)\b",
        re.IGNORECASE,
    ),
    "provider_read": re.compile(
        r"(?:^|\berror:\s+)(?:reading|retrieving|listing)\b", re.IGNORECASE | re.MULTILINE
    ),
    "provider_write": re.compile(
        r"(?:^|\berror:\s+)(?:creating|updating|deleting|waiting for)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    "reference_error": re.compile(
        r"\b(?:reference to (?:undeclared|unknown)|invalid reference|unsupported reference)\b",
        re.IGNORECASE,
    ),
    "reference_to_undeclared_resource": re.compile(
        r"\breference to undeclared resource\b", re.IGNORECASE
    ),
    "request_disallowed_by_policy": re.compile(r"\brequestdisallowedbypolicy\b", re.IGNORECASE),
    "resource_already_exists": re.compile(r"\balready exists\b", re.IGNORECASE),
    "resource_lock": re.compile(r"\bscopelocked\b", re.IGNORECASE),
    "resource_not_found": re.compile(
        r"\b(?:parentresource|resourcegroup|resource)notfound\b", re.IGNORECASE
    ),
    "resource_provider_registration": re.compile(
        r"\bresource providers?\b[^\n]{0,80}\bregist", re.IGNORECASE
    ),
    "state_lock": re.compile(r"\bstate lock\b", re.IGNORECASE),
    "subscription_not_registered": re.compile(
        r"\b(?:subscriptionnotregistered|missingsubscriptionregistration)\b", re.IGNORECASE
    ),
    "throttling": re.compile(
        r"\b(?:toomanyrequests|too many requests|throttl(?:ed|ing)|rate limit(?:ed)?"
        r"|retry-after|429)\b",
        re.IGNORECASE,
    ),
    "timeout": re.compile(r"\b(?:timed out|timeout|deadline exceeded)\b", re.IGNORECASE),
    "token_acquisition": re.compile(
        r"\b(?:failed to request token|metadata endpoint|imds|managedidentitycredential"
        r"|(?:obtain|acquir)(?:e|ing)? (?:an? )?(?:authorization |access )?token"
        r"|token request)\b",
        re.IGNORECASE,
    ),
    "unsupported_attribute": re.compile(
        r"\bunsupported (?:attribute|argument|block type)\b", re.IGNORECASE
    ),
}


def _messages(lines: Iterable[str]) -> Iterable[Mapping[str, Any]]:
    for line in lines:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, Mapping):
            yield message


def _address(value: object) -> str | None:
    return value if isinstance(value, str) and ADDRESS.fullmatch(value) else None


def project(lines: Iterable[str], *, stage: str) -> list[str]:
    """Return the allowlisted projection lines for one Terraform JSON UI log."""

    if stage not in STAGES:
        raise ValueError(f"unsupported Terraform stage: {stage}")
    errors = 0
    addresses: set[str] = set()
    codes: set[str] = set()
    categories: set[str] = set()
    for message in _messages(lines):
        kind = message.get("type")
        if stage == "apply" and kind == "apply_errored":
            hook = message.get("hook")
            resource = hook.get("resource") if isinstance(hook, Mapping) else None
            address = _address(resource.get("addr") if isinstance(resource, Mapping) else None)
            if address:
                addresses.add(address)
            continue
        if kind != "diagnostic":
            continue
        diagnostic = message.get("diagnostic")
        if not isinstance(diagnostic, Mapping) or diagnostic.get("severity") != "error":
            continue
        errors += 1
        address = _address(diagnostic.get("address"))
        if address:
            addresses.add(address)
        text = "\n".join(
            value
            for value in (diagnostic.get("summary"), diagnostic.get("detail"))
            if isinstance(value, str)
        )
        codes.update(match for pattern in CODE_PATTERNS for match in pattern.findall(text))
        codes.update(KNOWN_CODES.findall(text))
        codes.update(
            "HTTP" + match for pattern in STATUS_PATTERNS for match in pattern.findall(text)
        )
        categories.update(
            name for name, pattern in CATEGORY_PATTERNS.items() if pattern.search(text)
        )
    prefix = f"Terraform {stage} diagnostic"
    return [
        f"{prefix} errors: {errors}",
        f"{prefix} categories: " + (", ".join(sorted(categories)) or "unclassified"),
        f"{prefix} addresses: " + (", ".join(sorted(addresses)) or "unavailable"),
        f"{prefix} Azure codes: " + (", ".join(sorted(codes)) or "unavailable"),
    ]


def main(argv: Sequence[str]) -> int:
    if len(argv) != 2 or argv[0] not in STAGES:
        print("usage: terraform_diagnostics.py {plan|apply} <terraform-json-log>", file=sys.stderr)
        return 2
    try:
        raw = Path(argv[1]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        print(f"Terraform {argv[0]} diagnostic log unavailable.", file=sys.stderr)
        return 1
    for line in project(raw.splitlines(), stage=argv[0]):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
