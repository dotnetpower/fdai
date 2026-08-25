#!/usr/bin/env python3
"""Build and run the bounded deployment-runner connectivity preflight."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_SCHEMA = "fdai.network-connectivity-manifest.v1"
_STATE_TARGETS = (
    ("event-bus-primary", "event_bus_kafka_bootstrap", 9093),
    ("event-bus-operational", "event_bus_operational_kafka_bootstrap", 9093),
    ("postgres", "postgres_fqdn", 5432),
    ("key-vault", "key_vault_uri", 443),
    ("container-registry", "container_registry_login_server", 443),
    ("azure-openai", "llm_endpoint", 443),
)


def _json_object(raw: str, *, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def build_manifest(
    hosts: list[str],
    *,
    terraform_outputs: dict[str, str],
    private_networking: bool,
    premium_acr: bool,
    extra_checks: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one validated connectivity manifest without performing I/O."""
    if not all(isinstance(host, str) and host.strip() for host in hosts):
        raise ValueError("egress hosts must be non-empty strings")
    checks: list[dict[str, Any]] = [
        {
            "id": f"egress-{index:02d}",
            "host": host,
            "port": 443,
            "required": True,
            "expected_ip": "any",
        }
        for index, host in enumerate(hosts, start=1)
    ]
    for check_id, output_name, port in _STATE_TARGETS:
        value = terraform_outputs.get(output_name, "").strip()
        if not value:
            continue
        parsed = urlsplit(value if "://" in value else f"//{value}")
        if not parsed.hostname:
            raise ValueError(f"Terraform output for {check_id} has no hostname")
        expected_ip = (
            "private"
            if private_networking and (check_id != "container-registry" or premium_acr)
            else "public"
        )
        checks.append(
            {
                "id": check_id,
                "host": parsed.hostname,
                "port": port,
                "required": True,
                "expected_ip": expected_ip,
            }
        )
    if extra_checks is not None:
        if extra_checks.get("schema_version") != _SCHEMA or not isinstance(
            extra_checks.get("checks"), list
        ):
            raise ValueError("PREFLIGHT_NETWORK_CHECKS_JSON is not a valid manifest")
        checks.extend(extra_checks["checks"])
    return {"schema_version": _SCHEMA, "checks": checks}


def _terraform_outputs(terraform_dir: Path) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for _check_id, output_name, _port in _STATE_TARGETS:
        result = subprocess.run(
            ["terraform", f"-chdir={terraform_dir}", "output", "-raw", output_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            outputs[output_name] = result.stdout.strip()
    return outputs


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terraform-dir", type=Path, required=True)
    parser.add_argument("--egress-hosts-json", required=True)
    parser.add_argument("--extra-checks-json", default="")
    parser.add_argument("--private-networking", action="store_true")
    parser.add_argument("--premium-acr", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    hosts = json.loads(args.egress_hosts_json)
    if not isinstance(hosts, list):
        raise SystemExit("PREFLIGHT_EGRESS_HOSTS_JSON must be an array")
    extra = (
        _json_object(args.extra_checks_json, label="PREFLIGHT_NETWORK_CHECKS_JSON")
        if args.extra_checks_json.strip()
        else None
    )
    manifest = build_manifest(
        hosts,
        terraform_outputs=_terraform_outputs(args.terraform_dir),
        private_networking=args.private_networking,
        premium_acr=args.premium_acr,
        extra_checks=extra,
    )
    script_dir = Path(__file__).resolve().parent
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fdai-runner-preflight-") as temporary:
        root = Path(temporary)
        hosts_path = root / "egress-hosts.json"
        manifest_path = root / "network-manifest.json"
        egress_path = root / "egress.json"
        network_path = root / "network.json"
        hosts_path.write_text(json.dumps(hosts), encoding="utf-8")
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        _run(
            [
                "python3",
                str(script_dir / "check-runner-egress.py"),
                str(hosts_path),
                "--output",
                str(egress_path),
                "--timeout-seconds",
                "5",
            ]
        )
        _run(
            [
                "python3",
                str(script_dir / "check-network-connectivity.py"),
                "--profile",
                "custom",
                "--manifest",
                str(manifest_path),
                "--redact",
                "--output",
                str(network_path),
                "--timeout-seconds",
                "5",
            ]
        )
        with egress_path.open(encoding="utf-8") as stream:
            evidence = json.load(stream)
        with network_path.open(encoding="utf-8") as stream:
            evidence["network_connectivity"] = json.load(stream)
        args.output.write_text(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
