"""Capture one exact local-human authority receipt for delegated Run Command staging."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.deployment_deadline import DeploymentDeadline
from fdai_deployment_cli.private_output import read_private_bytes, write_private_bytes
from run_command_authority import capture_transport_authority


def _read(path: Path, label: str) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=1024 * 1024),
        label=label,
        max_bytes=1024 * 1024,
    )


def _capture(command: tuple[str, ...], *, timeout: int) -> str:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    ).stdout


def main() -> int:
    """Validate current human authority and write one private delegated receipt."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, required=True)
    parser.add_argument("--receiver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    try:
        bundle_receipt = _read(args.bundle_receipt, "execution bundle receipt")
        operation_id = bundle_receipt.get("operation_id")
        receipt_digest = bundle_receipt.get("receipt_digest")
        if not isinstance(operation_id, str) or not isinstance(receipt_digest, str):
            raise ValueError("execution bundle receipt identity is invalid")
        receiver_digest = hashlib.sha256(
            read_private_bytes(args.receiver, max_bytes=4 * 1024 * 1024)
        ).hexdigest()
        receipt = capture_transport_authority(
            target=_read(args.target, "run command transfer target"),
            profile_value=_read(args.profile, "run command provision profile"),
            approval=_read(args.approval, "run command transport approval"),
            operation_id=operation_id,
            bundle_receipt_digest=receipt_digest,
            receiver_digest=receiver_digest,
            capture=_capture,
            deadline=DeploymentDeadline(args.timeout_seconds),
        )
        write_private_bytes(args.output, canonical_bytes(receipt))
    except (OSError, ValueError, subprocess.SubprocessError):
        print(
            "run command authority capture failed; no authority receipt was written",
            file=sys.stderr,
        )
        return 3
    print(canonical_bytes(receipt).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
