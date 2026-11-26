"""Transfer an execution bundle through a private relay and fixed Azure Run Command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.contracts import canonical_bytes, load_json_object
from fdai_deployment_cli.private_output import read_private_bytes
from run_command_bootstrap import (
    POWERSHELL_BOOTSTRAP as POWERSHELL_BOOTSTRAP,
)
from run_command_bootstrap import (
    build_run_command as build_run_command,
)
from run_command_private_relay import PrivateRelay
from run_command_transfer import (
    capture as _default_capture,
)
from run_command_transfer import (
    invocation_claim_record as invocation_claim_record,
)
from run_command_transfer import (
    transfer_claim as transfer_claim,
)
from run_command_transfer import (
    transfer_execution_bundle as _transfer_execution_bundle,
)
from run_command_transfer import (
    transfer_parameters as transfer_parameters,
)
from run_command_transfer import (
    validate_host_result as validate_host_result,
)

_capture = _default_capture
_relay_factory = PrivateRelay


def transfer_execution_bundle(
    *,
    work_dir: Path,
    bundle: Path,
    bundle_receipt: dict[str, object],
    receiver: Path,
    receiver_digest: str,
    target: dict[str, object],
    profile: dict[str, object],
    approval: dict[str, object],
    authority_receipt: dict[str, object] | None = None,
    timeout_seconds: int,
) -> dict[str, object]:
    """Stage one exact bundle while preserving the public transport API."""

    return _transfer_execution_bundle(
        work_dir=work_dir,
        bundle=bundle,
        bundle_receipt=bundle_receipt,
        receiver=receiver,
        receiver_digest=receiver_digest,
        target=target,
        profile=profile,
        approval=approval,
        authority_receipt=authority_receipt,
        timeout_seconds=timeout_seconds,
        capture=_capture,
        relay_factory=_relay_factory,
    )


def _read(path: Path, label: str) -> dict[str, object]:
    return load_json_object(
        read_private_bytes(path, max_bytes=1024 * 1024),
        label=label,
        max_bytes=1024 * 1024,
    )


def main() -> int:
    """Stage one private bundle using only private local descriptor inputs."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--bundle-receipt", type=Path, required=True)
    parser.add_argument("--receiver", type=Path, required=True)
    parser.add_argument("--receiver-digest", required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--authority-receipt", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=2400)
    args = parser.parse_args()
    try:
        result = transfer_execution_bundle(
            work_dir=args.work_dir,
            bundle=args.bundle,
            bundle_receipt=_read(args.bundle_receipt, "execution bundle receipt"),
            receiver=args.receiver,
            receiver_digest=args.receiver_digest,
            target=_read(args.target, "run command transfer target"),
            profile=_read(args.profile, "run command provision profile"),
            approval=_read(args.approval, "run command transport approval"),
            authority_receipt=(
                _read(args.authority_receipt, "run command transport authority receipt")
                if args.authority_receipt is not None
                else None
            ),
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        print("run command bundle transport failed; preserve retained evidence", file=sys.stderr)
        return 3
    print(canonical_bytes(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
