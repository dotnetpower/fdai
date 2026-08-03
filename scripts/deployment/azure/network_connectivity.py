"""Bounded FDAI DNS, IP policy, TCP probe, and action-report engine."""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import re
import socket
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit

REPORT_SCHEMA: Final[str] = "fdai.network-connectivity-report.v1"
MANIFEST_SCHEMA: Final[str] = "fdai.network-connectivity-manifest.v1"
MAX_CHECKS: Final[int] = 64
DEFAULT_TIMEOUT_SECONDS: Final[float] = 5.0
PROFILES: Final[tuple[str, ...]] = ("runtime-private", "runtime-public", "deploy-runner", "custom")
_ID = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_HOST = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)
_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]*$")
_IP_POLICIES = frozenset({"any", "private", "public"})
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)

Resolver = Callable[[str, int], tuple[str, ...]]
Connector = Callable[[str, int, float], None]


class ConnectivityInputError(RuntimeError):
    """Connectivity input is invalid or unsafe to execute."""


@dataclass(frozen=True, slots=True)
class EndpointCheck:
    id: str
    host: str
    port: int
    required: bool
    expected_ip: str


def load_env_file(path: Path) -> dict[str, str]:
    """Read literal KEY=VALUE entries without evaluating shell syntax."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        key, separator, value = line.partition("=")
        if not separator or not _ENV_KEY.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def parse_manifest(payload: object) -> tuple[EndpointCheck, ...]:
    if not isinstance(payload, dict) or payload.get("schema_version") != MANIFEST_SCHEMA:
        raise ConnectivityInputError(f"manifest schema_version MUST be {MANIFEST_SCHEMA}")
    raw_checks = payload.get("checks")
    if not isinstance(raw_checks, list) or not raw_checks or len(raw_checks) > MAX_CHECKS:
        raise ConnectivityInputError("manifest checks MUST contain 1-64 entries")
    checks = tuple(_parse_manifest_check(item) for item in raw_checks)
    _require_unique_ids(checks)
    return checks


def _parse_manifest_check(raw: object) -> EndpointCheck:
    if not isinstance(raw, dict):
        raise ConnectivityInputError("each manifest check MUST be an object")
    check_id = raw.get("id")
    host = raw.get("host")
    port = raw.get("port")
    required = raw.get("required")
    expected_ip = raw.get("expected_ip")
    if not isinstance(check_id, str) or not _ID.fullmatch(check_id):
        raise ConnectivityInputError("check id MUST be a lowercase ASCII slug")
    if not isinstance(host, str) or not _valid_host(host):
        raise ConnectivityInputError(f"check {check_id} host MUST be a DNS name or IP address")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConnectivityInputError(f"check {check_id} port MUST be in [1, 65535]")
    if not isinstance(required, bool):
        raise ConnectivityInputError(f"check {check_id} required MUST be boolean")
    if not isinstance(expected_ip, str) or expected_ip not in _IP_POLICIES:
        raise ConnectivityInputError(
            f"check {check_id} expected_ip MUST be any, private, or public"
        )
    return EndpointCheck(check_id, host.casefold(), port, required, expected_ip)


def build_checks(
    profile: str,
    env: Mapping[str, str],
    manifest_checks: Sequence[EndpointCheck],
) -> tuple[tuple[EndpointCheck, ...], tuple[dict[str, object], ...]]:
    """Build profile defaults plus endpoints discovered from known env keys."""
    if profile not in PROFILES:
        raise ConnectivityInputError(f"profile MUST be one of {', '.join(PROFILES)}")
    checks: list[EndpointCheck] = list(_profile_defaults(profile))
    issues: list[dict[str, object]] = []
    if profile.startswith("runtime-"):
        data_policy = "private" if profile == "runtime-private" else "public"
        kafka = env.get("KAFKA_BOOTSTRAP_SERVERS") or env.get("FDAI_KAFKA_BOOTSTRAP_SERVERS", "")
        postgres = env.get("POSTGRES_HOST", "")
        if kafka:
            checks.extend(_checks_from_value("event-bus-primary", kafka, 9093, True, data_policy))
        else:
            issues.append(_missing_issue("event-bus-primary", "KAFKA_BOOTSTRAP_SERVERS"))
        if postgres:
            checks.extend(_checks_from_value("state-store", postgres, 5432, True, data_policy))
        else:
            issues.append(_missing_issue("state-store", "POSTGRES_HOST"))
        optional_sources = (
            (
                "event-bus-auxiliary",
                env.get("FDAI_AUXILIARY_KAFKA_BOOTSTRAP_SERVERS", ""),
                9093,
                data_policy,
            ),
            ("model-endpoint", env.get("FDAI_LLM_ENDPOINT", ""), 443, data_policy),
            ("prometheus", env.get("FDAI_PROMETHEUS_ENDPOINT", ""), 443, "any"),
            ("email", env.get("FDAI_EMAIL_ENDPOINT", ""), 443, "any"),
            (
                "dev-operations-gateway",
                env.get("FDAI_DEV_OPERATIONS_GATEWAY_URL", ""),
                443,
                "any",
            ),
        )
        for check_id, value, port, expected_ip in optional_sources:
            if value:
                checks.extend(_checks_from_value(check_id, value, port, False, expected_ip))
    checks.extend(manifest_checks)
    if len(checks) > MAX_CHECKS:
        raise ConnectivityInputError("combined checks exceed the 64-entry limit")
    _require_unique_ids(checks)
    return tuple(checks), tuple(issues)


def _profile_defaults(profile: str) -> tuple[EndpointCheck, ...]:
    if profile == "custom":
        return ()
    defaults = [
        EndpointCheck("identity", "login.microsoftonline.com", 443, True, "public"),
        EndpointCheck("management", "management.azure.com", 443, True, "any"),
    ]
    if profile == "deploy-runner":
        defaults.extend(
            (
                EndpointCheck("github", "github.com", 443, True, "public"),
                EndpointCheck("github-api", "api.github.com", 443, True, "public"),
            )
        )
    return tuple(defaults)


def _checks_from_value(
    base_id: str,
    value: str,
    default_port: int,
    required: bool,
    expected_ip: str,
) -> tuple[EndpointCheck, ...]:
    targets = tuple(_parse_target(part.strip(), default_port) for part in value.split(",") if part)
    if not targets:
        raise ConnectivityInputError(f"{base_id} endpoint value is empty")
    return tuple(
        EndpointCheck(
            base_id if len(targets) == 1 else f"{base_id}-{index}",
            host,
            port,
            required,
            expected_ip,
        )
        for index, (host, port) in enumerate(targets, start=1)
    )


def _parse_target(value: str, default_port: int) -> tuple[str, int]:
    parsed = urlsplit(value if "://" in value else f"//{value}")
    try:
        configured_port = parsed.port
    except ValueError as exc:
        raise ConnectivityInputError("endpoint contains an invalid port") from exc
    port = default_port if configured_port is None else configured_port
    if not 1 <= port <= 65535:
        raise ConnectivityInputError("endpoint contains an invalid port")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConnectivityInputError("endpoint MUST be an origin without path, query, or fragment")
    host = parsed.hostname or ""
    if parsed.username or parsed.password or not _valid_host(host):
        raise ConnectivityInputError("endpoint MUST contain a DNS name or IP address")
    return host.casefold(), port


def _valid_host(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return _HOST.fullmatch(host) is not None


def _require_unique_ids(checks: Sequence[EndpointCheck]) -> None:
    ids = [check.id for check in checks]
    if len(ids) != len(set(ids)):
        raise ConnectivityInputError("check ids MUST be unique after profile composition")


def _missing_issue(check_id: str, env_key: str) -> dict[str, object]:
    return {
        "id": check_id,
        "status": "fail",
        "reason": "configuration_missing",
        "action": f"Set {env_key} or supply an equivalent manifest check.",
    }


def run_checks(
    checks: Sequence[EndpointCheck],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    workers: int = 8,
    resolver: Resolver | None = None,
    connector: Connector | None = None,
) -> dict[str, object]:
    if not checks or len(checks) > MAX_CHECKS:
        raise ConnectivityInputError("checks MUST contain 1-64 entries")
    if timeout_seconds <= 0 or timeout_seconds > 30:
        raise ConnectivityInputError("timeout_seconds MUST be in (0, 30]")
    if workers <= 0 or workers > 16:
        raise ConnectivityInputError("workers MUST be in [1, 16]")
    resolve = resolver or _resolve
    connect = connector or _connect
    with ThreadPoolExecutor(max_workers=min(workers, len(checks))) as executor:
        results = list(
            executor.map(lambda check: _probe_one(check, timeout_seconds, resolve, connect), checks)
        )
    return _report_from_results(results)


def _probe_one(
    check: EndpointCheck,
    timeout_seconds: float,
    resolver: Resolver,
    connector: Connector,
) -> dict[str, object]:
    base = asdict(check)
    try:
        addresses = tuple(sorted(set(resolver(check.host, check.port))))
    except OSError:
        return _failed_result(base, check.required, "dns_resolution_failed", ())
    if not addresses:
        return _failed_result(base, check.required, "dns_resolution_failed", ())
    if not _matches_policy(addresses, check.expected_ip):
        return _failed_result(base, check.required, "ip_policy_mismatch", addresses)
    reachable: list[str] = []
    for address in addresses:
        try:
            connector(address, check.port, timeout_seconds)
        except OSError:
            continue
        reachable.append(address)
        break
    if not reachable:
        return _failed_result(base, check.required, "tcp_unreachable", addresses)
    return {
        **base,
        "status": "pass",
        "reason": "reachable",
        "addresses": list(addresses),
        "reachable_addresses": reachable,
    }


def _failed_result(
    base: dict[str, object], required: bool, reason: str, addresses: Sequence[str]
) -> dict[str, object]:
    return {
        **base,
        "status": "fail" if required else "warn",
        "reason": reason,
        "addresses": list(addresses),
        "reachable_addresses": [],
    }


def _resolve(host: str, port: int) -> tuple[str, ...]:
    try:
        ipaddress.ip_address(host)
        return (host,)
    except ValueError:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return tuple(sorted({str(record[4][0]) for record in records}))


def _connect(address: str, port: int, timeout_seconds: float) -> None:
    with socket.create_connection((address, port), timeout=timeout_seconds):
        return


def _matches_policy(addresses: Sequence[str], policy: str) -> bool:
    if policy == "any":
        return True
    parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    if policy == "private":
        return all(
            address.is_loopback
            or any(
                address.version == network.version and address in network
                for network in _PRIVATE_NETWORKS
            )
            for address in parsed
        )
    return all(address.is_global for address in parsed)


def _report_from_results(results: list[dict[str, object]]) -> dict[str, object]:
    counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("pass", "warn", "fail")
    }
    status = "fail" if counts["fail"] else "warn" if counts["warn"] else "pass"
    return {
        "schema_version": REPORT_SCHEMA,
        "status": status,
        "summary": counts,
        "checks": results,
        "actions_required": [
            {"id": str(result["id"]), "action": _action_for(result)}
            for result in results
            if result["status"] != "pass"
        ],
    }


def add_input_issues(
    report: dict[str, object], issues: Sequence[dict[str, object]]
) -> dict[str, object]:
    if not issues:
        return report
    updated = copy.deepcopy(report)
    checks = cast(list[dict[str, object]], updated["checks"])
    actions = cast(list[dict[str, str]], updated["actions_required"])
    summary = cast(dict[str, int], updated["summary"])
    checks.extend(issues)
    actions.extend({"id": str(issue["id"]), "action": str(issue["action"])} for issue in issues)
    summary["fail"] += len(issues)
    updated["status"] = "fail"
    return updated


def _action_for(result: Mapping[str, object]) -> str:
    check_id = str(result["id"])
    reason = result["reason"]
    if reason == "dns_resolution_failed":
        return f"Configure DNS forwarding and private-zone links for {check_id}."
    if reason == "ip_policy_mismatch":
        return (
            f"Fix split DNS for {check_id}; it must resolve to "
            f"{result['expected_ip']} address space before opening the port."
        )
    return f"Allow TCP {result['port']} for {check_id} in NSG/firewall/UDR and verify its route."


def redact_report(report: Mapping[str, object]) -> dict[str, object]:
    """Remove deployment hostnames and addresses from a shareable report."""
    redacted = copy.deepcopy(dict(report))
    checks = redacted.get("checks")
    if not isinstance(checks, list):
        return redacted
    for item in checks:
        if not isinstance(item, dict) or "host" not in item:
            continue
        host = str(item.pop("host"))
        digest = hashlib.sha256(host.casefold().encode("utf-8")).hexdigest()[:16]
        item["host_ref"] = f"sha256:{digest}"
        item.pop("addresses", None)
        item.pop("reachable_addresses", None)
    return redacted


def exit_code(report: Mapping[str, object]) -> int:
    return 1 if report.get("status") == "fail" else 0
