"""Build the fixed non-secret private-relay Run Command invocation."""

from __future__ import annotations

import ipaddress
import re

GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
AZURE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._()-]{0,89}")
OPERATION = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
DIGEST = re.compile(r"[0-9a-f]{64}")
MAX_BUNDLE_BYTES = 512 * 1024 * 1024
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
PARAMETERS = (
    "bundle_digest",
    "bundle_size",
    "claim_digest",
    "file_count",
    "inventory_digest",
    "operation_id",
    "recovery_mode",
    "receiver_digest",
    "relay_certificate_digest",
    "relay_host",
    "relay_port",
)

POWERSHELL_BOOTSTRAP = r"""param(
  [string]$bundle_digest,
  [string]$bundle_size,
    [string]$claim_digest,
  [string]$receiver_digest,
    [string]$operation_id,
    [string]$recovery_mode,
    [string]$file_count,
    [string]$inventory_digest,
    [string]$relay_certificate_digest,
    [string]$relay_host,
    [string]$relay_port
)
$ErrorActionPreference = "Stop"
$shell = @'
set -eu
root="/var/lib/fdai/run-command-$FDAI_OPERATION_ID"
if [ "$FDAI_RECOVERY_MODE" = fresh ]; then
    test ! -e "$root" && test ! -L "$root"
    install -d -m 0700 "$root"
else
    test "$FDAI_RECOVERY_MODE" = verify
    test ! -L "$root"
    test -d "$root/execution" && test ! -L "$root/execution"
fi
test "$(stat -c '%u:%a' "$root")" = "0:700"
umask 077
certificate="$root/relay-certificate.pem"
if [ "$FDAI_RECOVERY_MODE" = verify ]; then
        rm -f "$certificate" "$root/receiver.pyz" "$root/bundle.tar.gz" \
                "$root/host-result.json"
fi
for transient in "$certificate" "$root/receiver.pyz" "$root/bundle.tar.gz" \
  "$root/host-result.json"; do
    test ! -e "$transient" && test ! -L "$transient"
done
base="https://$FDAI_RELAY_HOST:$FDAI_RELAY_PORT/$FDAI_OPERATION_ID"
curl --proto '=https' --tlsv1.2 --insecure --fail --silent --show-error \
    --max-time 60 "$base/certificate.pem" --output "$certificate"
test "$(sha256sum "$certificate" | cut -d' ' -f1)" = \
    "$FDAI_RELAY_CERTIFICATE_DIGEST"
download() {
        curl --proto '=https' --tlsv1.2 --cacert "$certificate" \
            --fail --silent --show-error --max-time 600 "$base/$1" --output "$2"
}
download receiver.pyz "$root/receiver.pyz"
test "$(sha256sum "$root/receiver.pyz" | cut -d' ' -f1)" = "$FDAI_RECEIVER_DIGEST"
chmod 0600 "$root/receiver.pyz"
if [ "$FDAI_RECOVERY_MODE" = fresh ]; then
        download bundle.tar.gz "$root/bundle.tar.gz"
        test "$(stat -c %s "$root/bundle.tar.gz")" = "$FDAI_BUNDLE_SIZE"
        test "$(sha256sum "$root/bundle.tar.gz" | cut -d' ' -f1)" = "$FDAI_BUNDLE_DIGEST"
        chmod 0600 "$root/bundle.tar.gz"
        python3 -I "$root/receiver.pyz" \
            --archive "$root/bundle.tar.gz" \
            --destination "$root/execution" \
            --bundle-digest "$FDAI_BUNDLE_DIGEST" \
            --operation-id "$FDAI_OPERATION_ID" \
            --claim-digest "$FDAI_CLAIM_DIGEST" > "$root/host-result.json"
else
        python3 -I "$root/receiver.pyz" \
            --destination "$root/execution" \
            --bundle-digest "$FDAI_BUNDLE_DIGEST" \
    --operation-id "$FDAI_OPERATION_ID" \
    --claim-digest "$FDAI_CLAIM_DIGEST" \
            --verify-existing > "$root/host-result.json"
fi
python3 - "$root/host-result.json" "$FDAI_FILE_COUNT" "$FDAI_INVENTORY_DIGEST" <<'PY'
import json,sys
value=json.load(open(sys.argv[1]))
assert value["file_count"] == int(sys.argv[2])
assert value["inventory_digest"] == sys.argv[3]
PY
curl --proto '=https' --tlsv1.2 --cacert "$certificate" \
    --fail --silent --show-error --max-time 120 -X PUT \
    -H 'Content-Type: application/json' \
    --data-binary "@$root/host-result.json" "$base/host-result.json"
rm -f "$certificate" "$root/receiver.pyz" "$root/bundle.tar.gz" \
    "$root/host-result.json"
test ! -e "$certificate" && test ! -e "$root/receiver.pyz" \
    && test ! -e "$root/bundle.tar.gz" && test ! -e "$root/host-result.json"
test "$(find "$root" -mindepth 1 -maxdepth 1 -printf '%f\n')" = execution
python3 - "$root" <<'PY'
import os,sys
descriptor=os.open(sys.argv[1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try: os.fsync(descriptor)
finally: os.close(descriptor)
PY
echo FDAI_RUN_COMMAND_COMPLETED=true
'@
$environment = @(
  "FDAI_BUNDLE_DIGEST=$bundle_digest",
  "FDAI_BUNDLE_SIZE=$bundle_size",
    "FDAI_CLAIM_DIGEST=$claim_digest",
  "FDAI_RECEIVER_DIGEST=$receiver_digest",
    "FDAI_OPERATION_ID=$operation_id",
    "FDAI_RECOVERY_MODE=$recovery_mode",
    "FDAI_FILE_COUNT=$file_count",
    "FDAI_INVENTORY_DIGEST=$inventory_digest",
    "FDAI_RELAY_CERTIFICATE_DIGEST=$relay_certificate_digest",
    "FDAI_RELAY_HOST=$relay_host",
    "FDAI_RELAY_PORT=$relay_port"
)
$output = & wsl.exe -u root -e env @environment sh -lc $shell
if ($LASTEXITCODE -ne 0) { throw "fixed WSL receiver failed" }
$output | Select-String -SimpleMatch 'FDAI_RUN_COMMAND_COMPLETED=true'
"""


def build_run_command(
    *,
    vm_resource_id: str,
    parameters: dict[str, object],
) -> tuple[str, ...]:
    """Build one fixed-script invocation from non-secret allowlisted values."""

    if (
        not vm_resource_id.startswith("/subscriptions/")
        or "/resourceGroups/" not in vm_resource_id
        or "/providers/Microsoft.Compute/virtualMachines/" not in vm_resource_id
    ):
        raise ValueError("run command target is invalid")
    if set(parameters) != set(PARAMETERS):
        raise ValueError("run command parameter inventory is invalid")
    validate_parameters(parameters)
    return (
        "az",
        "vm",
        "run-command",
        "invoke",
        "--ids",
        vm_resource_id,
        "--command-id",
        "RunPowerShellScript",
        "--scripts",
        POWERSHELL_BOOTSTRAP,
        "--only-show-errors",
        "--output",
        "json",
        "--parameters",
        *(f"{name}={parameters[name]}" for name in PARAMETERS),
    )


def validate_parameters(parameters: dict[str, object]) -> None:
    """Reject every dynamic value outside the fixed non-secret parameter contract."""

    bundle_size = _exact_int(parameters.get("bundle_size"))
    file_count = _exact_int(parameters.get("file_count"))
    relay_port = _exact_int(parameters.get("relay_port"))
    if (
        not isinstance(parameters.get("operation_id"), str)
        or OPERATION.fullmatch(str(parameters["operation_id"])) is None
        or bundle_size is None
        or not 0 < bundle_size <= MAX_BUNDLE_BYTES
        or file_count is None
        or not 0 < file_count <= 20_000
        or parameters.get("recovery_mode") not in {"fresh", "verify"}
        or relay_port is None
        or not 1024 <= relay_port <= 65_535
    ):
        raise ValueError("run command parameter value is invalid")
    relay_host = parameters.get("relay_host")
    if not isinstance(relay_host, str) or not _private_ipv4(relay_host):
        raise ValueError("run command relay host is invalid")
    for name in (
        "bundle_digest",
        "claim_digest",
        "inventory_digest",
        "receiver_digest",
        "relay_certificate_digest",
    ):
        value = parameters.get(name)
        if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
            raise ValueError("run command parameter digest is invalid")


def validate_target(target: dict[str, object]) -> None:
    """Validate the private exact target descriptor."""

    if (
        set(target)
        != {
            "schema_version",
            "subscription_id",
            "tenant_id",
            "resource_group",
            "vm_name",
            "vm_resource_id",
            "identity_client_id",
            "identity_principal_id",
            "relay_private_ip",
            "relay_port",
            "host_private_ip",
            "target_binding",
        }
        or target.get("schema_version") != "fdai.run-command-private-relay-target.v1"
        or not isinstance(target.get("subscription_id"), str)
        or GUID.fullmatch(str(target["subscription_id"])) is None
        or not isinstance(target.get("tenant_id"), str)
        or GUID.fullmatch(str(target["tenant_id"])) is None
        or not isinstance(target.get("resource_group"), str)
        or AZURE_NAME.fullmatch(str(target["resource_group"])) is None
        or not isinstance(target.get("vm_name"), str)
        or AZURE_NAME.fullmatch(str(target["vm_name"])) is None
        or not isinstance(target.get("vm_resource_id"), str)
        or not str(target["vm_resource_id"]).startswith("/subscriptions/")
        or not isinstance(target.get("identity_client_id"), str)
        or GUID.fullmatch(str(target["identity_client_id"])) is None
        or not isinstance(target.get("identity_principal_id"), str)
        or GUID.fullmatch(str(target["identity_principal_id"])) is None
        or not isinstance(target.get("target_binding"), str)
        or DIGEST.fullmatch(str(target["target_binding"])) is None
    ):
        raise ValueError("run command transfer target is invalid")
    host_private_ip = target.get("host_private_ip")
    if (
        not isinstance(host_private_ip, str)
        or not _private_ipv4(host_private_ip)
        or host_private_ip == target.get("relay_private_ip")
    ):
        raise ValueError("run command transfer target is invalid")
    validate_parameters(
        {
            "bundle_digest": "0" * 64,
            "bundle_size": 1,
            "claim_digest": "0" * 64,
            "receiver_digest": "0" * 64,
            "file_count": 1,
            "inventory_digest": "0" * 64,
            "operation_id": "validation",
            "recovery_mode": "fresh",
            "relay_certificate_digest": "0" * 64,
            "relay_host": target["relay_private_ip"],
            "relay_port": target["relay_port"],
        }
    )


def _private_ipv4(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in PRIVATE_NETWORKS
    )


def _exact_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return value
