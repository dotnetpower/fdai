"""Verify the public AKS Store Demo domain against its LoadBalancer address."""

from __future__ import annotations

import ipaddress
import socket
import sys
import time
import urllib.error
import urllib.request

VERIFY_TIMEOUT_SECONDS = 600
RETRY_SECONDS = 10


def _resolved_addresses(hostname: str) -> set[str]:
    addresses: set[str] = set()
    for address in socket.getaddrinfo(hostname, 80, type=socket.SOCK_STREAM):
        resolved = address[4][0]
        if isinstance(resolved, str):
            addresses.add(resolved)
    return addresses


def _healthy(hostname: str) -> bool:
    request = urllib.request.Request(  # noqa: S310 - caller validates the fixed HTTP hostname.
        f"http://{hostname}/health",
        headers={"User-Agent": "fdai-scenario-lab"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            status = getattr(response, "status", None)
            return isinstance(status, int) and status == 200
    except (OSError, urllib.error.HTTPError):
        return False


def verify(hostname: str, expected_ip: str) -> bool:
    """Wait for DNS and HTTP health to match the observed LoadBalancer IP."""
    if not hostname.endswith(".cloudapp.azure.com") or hostname != hostname.lower():
        raise ValueError("store-front hostname must be a lowercase Azure cloudapp domain")
    expected = str(ipaddress.ip_address(expected_ip))
    deadline = time.monotonic() + VERIFY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if expected in _resolved_addresses(hostname) and _healthy(hostname):
                return True
        except socket.gaierror:
            pass
        time.sleep(RETRY_SECONDS)
    return False


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: verify_store_front_domain.py <hostname> <load-balancer-ip>", file=sys.stderr)
        return 2
    try:
        verified = verify(argv[1], argv[2])
    except ValueError as exc:
        print(f"verify_store_front_domain: {exc}", file=sys.stderr)
        return 2
    if not verified:
        print(
            "verify_store_front_domain: DNS and HTTP health verification timed out.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
