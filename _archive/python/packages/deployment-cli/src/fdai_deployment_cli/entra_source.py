"""Launch bounded Entra convergence from a private tracked-only source snapshot."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path

from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.doctor import azure_active_target_binding
from fdai_deployment_cli.entra_profiles import (
    load_control_profile,
    load_control_profile_descriptor,
    load_target_profile,
    load_target_profile_descriptor,
    open_private_profile,
)
from fdai_deployment_cli.private_output import read_private_bytes, write_private_output
from fdai_deployment_cli.source_input import SourceDeploymentInput, inspect_source
from fdai_deployment_cli.source_snapshot import materialize_source, verify_source_snapshot

_SAFE_ENVIRONMENT_KEYS = frozenset(
    {
        "AZURE_CONFIG_DIR",
        "CURL_CA_BUNDLE",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_FILE",
        "TERM",
        "TZ",
        "USER",
    }
)
_SNAPSHOT_CONTEXT = "entra-source-context.json"
_BOOTSTRAP = """
import os, runpy, sys
from pathlib import Path
from fdai_deployment_cli.source_snapshot import verify_source_snapshot
root = os.environ["FDAI_ENTRA_SNAPSHOT_ROOT"]
verify_source_snapshot(
    Path(os.environ["FDAI_ENTRA_SNAPSHOT_DIRECTORY"]),
    expected_digest=os.environ["FDAI_ENTRA_SNAPSHOT_DIGEST"],
)
sys.path[:0] = [
    root + "/scripts/deployment/azure",
    root + "/packages/deployment-cli/src",
]
runpy.run_path(
    root + "/scripts/deployment/azure/genesis_entra_operation.py",
    run_name="__main__",
)
""".strip()


def run_source_entra_operation(
    *,
    source: Path,
    work_dir: Path,
    target_profile_path: Path,
    control_profile_path: Path,
    apply: bool,
    output: str,
    timeout_seconds: int,
) -> int:
    """Verify the target before creating state, then execute only snapshotted bytes."""

    target_profile = load_target_profile(target_profile_path)
    control_profile = load_control_profile(control_profile_path)
    if target_profile.control_profile_digest != control_profile.digest:
        raise ValueError("Entra target profile does not bind the reviewed control profile")
    if apply and target_profile.environment != "dev":
        raise ValueError("Entra apply is supported only for a profile-bound dev target")
    active_binding = azure_active_target_binding()
    if active_binding is None or active_binding != target_profile.target_binding:
        raise ValueError("active Azure target does not match the private Entra target profile")
    if not work_dir.is_absolute():
        raise ValueError("Entra work directory MUST be absolute")
    if output not in {"text", "json"}:
        raise ValueError("Entra output format is invalid")
    if not 30 <= timeout_seconds <= 1800:
        raise ValueError("Entra operation timeout MUST be between 30 and 1800 seconds")
    source_input = inspect_source(source)
    _ensure_private_directory(work_dir)
    snapshot_directory, snapshot_digest = _prepare_snapshot(
        work_dir=work_dir,
        source=source_input,
        target_profile_digest=target_profile.digest,
        control_profile_digest=control_profile.digest,
    )
    snapshot_tree = snapshot_directory / "tree"
    entrypoint = snapshot_tree / "scripts/deployment/azure/genesis_entra_operation.py"
    if not entrypoint.is_file() or entrypoint.is_symlink():
        raise ValueError("verified Entra source snapshot is missing its identity entrypoint")

    target_descriptor = open_private_profile(target_profile_path)
    control_descriptor = open_private_profile(control_profile_path)
    try:
        if load_target_profile_descriptor(target_descriptor).digest != target_profile.digest:
            raise ValueError("Entra target profile changed after target validation")
        if load_control_profile_descriptor(control_descriptor).digest != control_profile.digest:
            raise ValueError("Entra control profile changed after target validation")
        command = [
            sys.executable,
            "-I",
            "-c",
            _BOOTSTRAP,
            "--work-dir",
            str(work_dir),
            "--output",
            output,
        ]
        if apply:
            command.append("--apply")
        process_environment = {
            key: value for key, value in os.environ.items() if key in _SAFE_ENVIRONMENT_KEYS
        }
        process_environment.update(
            {
                "PYTHONNOUSERSITE": "1",
                "FDAI_ENTRA_TARGET_PROFILE_FD": str(target_descriptor),
                "FDAI_ENTRA_CONTROL_PROFILE_FD": str(control_descriptor),
                "FDAI_ENTRA_SNAPSHOT_DIRECTORY": str(snapshot_directory),
                "FDAI_ENTRA_SNAPSHOT_ROOT": str(snapshot_tree),
                "FDAI_ENTRA_SNAPSHOT_DIGEST": snapshot_digest,
            }
        )
        verify_source_snapshot(snapshot_directory, expected_digest=snapshot_digest)
        return _run_identity_process(
            command,
            cwd=snapshot_tree,
            environment=process_environment,
            timeout_seconds=timeout_seconds,
            pass_fds=(target_descriptor, control_descriptor),
        )
    finally:
        os.close(target_descriptor)
        os.close(control_descriptor)


def _prepare_snapshot(
    *,
    work_dir: Path,
    source: SourceDeploymentInput,
    target_profile_digest: str,
    control_profile_digest: str,
) -> tuple[Path, str]:
    snapshot_directory = work_dir / "source-snapshot"
    context_path = work_dir / _SNAPSHOT_CONTEXT
    if context_path.exists():
        context = load_json_object(
            read_private_bytes(context_path, max_bytes=65_536),
            label="Entra source context",
            max_bytes=65_536,
        )
        if (
            set(context)
            != {
                "schema_version",
                "source_digest",
                "snapshot_digest",
                "target_profile_digest",
                "control_profile_digest",
            }
            or context.get("schema_version") != "fdai.entra-source-context.v1"
            or context.get("source_digest") != source.digest
            or context.get("target_profile_digest") != target_profile_digest
            or context.get("control_profile_digest") != control_profile_digest
            or not isinstance(context.get("snapshot_digest"), str)
        ):
            raise ValueError("retained Entra source context differs from current inputs")
        snapshot_digest = str(context["snapshot_digest"])
        verify_source_snapshot(snapshot_directory, expected_digest=snapshot_digest)
        return snapshot_directory, snapshot_digest
    if snapshot_directory.exists() or snapshot_directory.is_symlink():
        raise ValueError("unbound Entra source snapshot already exists")
    snapshot_digest = materialize_source(source, snapshot_directory)
    context = {
        "schema_version": "fdai.entra-source-context.v1",
        "source_digest": source.digest,
        "snapshot_digest": snapshot_digest,
        "target_profile_digest": target_profile_digest,
        "control_profile_digest": control_profile_digest,
    }
    write_private_output(
        context_path,
        json.dumps(context, sort_keys=True, separators=(",", ":")) + "\n",
    )
    return snapshot_directory, snapshot_digest


def _ensure_private_directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("Entra work directory MUST NOT be a symbolic link")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    details = path.stat()
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.geteuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise PermissionError("Entra work directory MUST be current-UID mode 0700")


def _run_identity_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
    pass_fds: tuple[int, ...],
) -> int:
    """Bound the identity coordinator and terminate its complete process group."""

    process = subprocess.Popen(  # noqa: S603 - fixed verified-snapshot bootstrap.
        command,
        cwd=cwd,
        env=environment,
        pass_fds=pass_fds,
        start_new_session=True,
    )
    try:
        return process.wait(timeout=timeout_seconds)
    except BaseException:
        for selected_signal, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 1)):
            try:
                os.killpg(process.pid, selected_signal)
            except ProcessLookupError:
                break
            try:
                process.wait(timeout=grace)
                if selected_signal == signal.SIGKILL:
                    break
            except subprocess.TimeoutExpired:
                continue
        raise
