"""Credentialed Azure CLI broker for exact, typed read-only command plans."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import signal
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fdai.shared.providers.command_runner import (
    CommandExecutionClass,
    CommandNetworkProfile,
    CommandOutputFormat,
    CommandPlan,
    CommandReceipt,
    CommandRunner,
    CommandStatus,
)

_RESOURCE_GROUP = re.compile(r"^[A-Za-z0-9_.()-]{1,90}$")
_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9_.()-]{1,128}$")
_RESOURCE_TYPE = re.compile(r"^[A-Za-z0-9_.-]{1,128}(?:/[A-Za-z0-9_.-]{1,128})?$")
_SUBSCRIPTION = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9-]{1,128}$")
_SECRET_MARKERS = (
    "AccountKey=",
    "SharedAccessKey=",
    "Bearer ",
    "accessToken",
    "refreshToken",
)


@dataclass(frozen=True, slots=True)
class AzureCliCommandRunnerConfig:
    subscription_id: str
    managed_identity_client_id: str
    executable: str = "/usr/bin/az"
    credential_profile: str = "azure.reader"
    timeout_seconds: float = 60.0
    max_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if _SUBSCRIPTION.fullmatch(self.subscription_id) is None:
            raise ValueError("subscription_id MUST be a bounded identifier")
        if _CLIENT_ID.fullmatch(self.managed_identity_client_id) is None:
            raise ValueError("managed_identity_client_id MUST be a bounded identifier")
        if not Path(self.executable).is_absolute():
            raise ValueError("executable MUST be an absolute path")
        if self.credential_profile != "azure.reader":
            raise ValueError("credential_profile MUST be 'azure.reader'")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds MUST be positive")
        if not 1024 <= self.max_output_bytes <= 5_000_000:
            raise ValueError("max_output_bytes MUST be in [1024, 5000000]")


@dataclass(frozen=True, slots=True)
class AzureCliProcessResult:
    return_code: int
    stdout: bytes
    stderr: bytes


AzureCliInvoker = Callable[
    [tuple[str, ...], Mapping[str, str], float, int],
    Awaitable[AzureCliProcessResult],
]


class AzureCliCommandRunner(CommandRunner):
    """Execute allowlisted Azure read plans under managed identity."""

    def __init__(
        self,
        config: AzureCliCommandRunnerConfig,
        *,
        invoker: AzureCliInvoker | None = None,
    ) -> None:
        self._config: Final = config
        self._invoke: Final = invoker or _invoke_process
        self._receipts: dict[str, CommandReceipt] = {}

    async def execute(self, plan: CommandPlan) -> CommandReceipt:
        _validate_plan(plan, self._config)
        if plan.dry_run:
            return CommandReceipt(
                status=CommandStatus.PLANNED,
                receipt_ref=_receipt_ref("azure-command-plan", plan),
            )
        prior = self._receipts.get(plan.idempotency_key)
        if prior is not None:
            return CommandReceipt(
                status=CommandStatus.ALREADY_APPLIED,
                receipt_ref=prior.receipt_ref,
                exit_code=prior.exit_code,
                already_existed=True,
            )
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="fdai-azure-cli-") as config_dir:
            os.chmod(config_dir, 0o700)
            env = _isolated_env(config_dir)
            login = await self._call(
                (
                    self._config.executable,
                    "login",
                    "--identity",
                    "--client-id",
                    self._config.managed_identity_client_id,
                    "--only-show-errors",
                    "--output",
                    "none",
                ),
                env,
            )
            if login.return_code != 0:
                return _failed_receipt(plan, login, started, "managed identity login failed")
            account = await self._call(
                (
                    self._config.executable,
                    "account",
                    "show",
                    "--subscription",
                    self._config.subscription_id,
                    "--query",
                    "id",
                    "--output",
                    "tsv",
                    "--only-show-errors",
                ),
                env,
            )
            if account.return_code != 0:
                return _failed_receipt(plan, account, started, "subscription check failed")
            actual_subscription = account.stdout.decode("utf-8", errors="replace").strip()
            if actual_subscription != self._config.subscription_id:
                return CommandReceipt(
                    status=CommandStatus.STOPPED,
                    receipt_ref=_receipt_ref("azure-command-stopped", plan),
                    exit_code=account.return_code,
                    stderr_tail="active Azure subscription does not match the trusted scope",
                    duration_ms=_duration_ms(started),
                )
            result = await self._call((self._config.executable, *plan.argv), env)
        if result.return_code != 0:
            return _failed_receipt(plan, result, started, "Azure CLI command failed")
        receipt = CommandReceipt(
            status=CommandStatus.SUCCEEDED,
            receipt_ref=_receipt_ref("azure-command", plan),
            exit_code=0,
            stdout_tail=_tail(result.stdout),
            stderr_tail=_safe_detail(result.stderr),
            duration_ms=_duration_ms(started),
        )
        self._receipts[plan.idempotency_key] = receipt
        return receipt

    async def _call(
        self,
        argv: tuple[str, ...],
        env: Mapping[str, str],
    ) -> AzureCliProcessResult:
        try:
            return await self._invoke(
                argv,
                env,
                self._config.timeout_seconds,
                self._config.max_output_bytes,
            )
        except TimeoutError:
            return AzureCliProcessResult(
                return_code=124,
                stdout=b"",
                stderr=b"command timed out",
            )
        except _OutputLimitExceededError:
            return AzureCliProcessResult(
                return_code=125,
                stdout=b"",
                stderr=b"command output exceeded its byte cap",
            )
        except OSError as exc:
            detail = f"Azure CLI unavailable: {type(exc).__name__}".encode()
            return AzureCliProcessResult(return_code=127, stdout=b"", stderr=detail)


def _validate_plan(plan: CommandPlan, config: AzureCliCommandRunnerConfig) -> None:
    if plan.command_version != 1 or plan.command_id not in _COMMAND_VALIDATORS:
        raise ValueError("Azure CLI broker accepts registered Azure read commands at v1 only")
    if plan.executable_ref != "azure.cli":
        raise ValueError("Azure CLI broker requires executable_ref 'azure.cli'")
    if plan.execution_class is not CommandExecutionClass.CLOUD_READ:
        raise ValueError("Azure CLI broker accepts cloud_read commands only")
    if plan.network_profile is not CommandNetworkProfile.AZURE_CONTROL_PLANE:
        raise ValueError("Azure CLI broker requires the Azure control-plane network profile")
    if plan.output_format is not CommandOutputFormat.JSON:
        raise ValueError("Azure CLI broker requires JSON output")
    if plan.credential_profile != config.credential_profile:
        raise ValueError("Azure CLI credential profile does not match the trusted binding")
    _COMMAND_VALIDATORS[plan.command_id](plan.argv, config.subscription_id)


def _validate_resource_list(argv: tuple[str, ...], subscription_id: str) -> None:
    _validate_option_argv(
        argv,
        prefix=("resource", "list", "--only-show-errors", "--output", "json"),
        optional={"--resource-group": _RESOURCE_GROUP, "--resource-type": _RESOURCE_TYPE},
        required={},
        subscription_id=subscription_id,
    )


def _validate_group_list(argv: tuple[str, ...], subscription_id: str) -> None:
    _validate_option_argv(
        argv,
        prefix=("group", "list", "--only-show-errors", "--output", "json"),
        optional={},
        required={},
        subscription_id=subscription_id,
    )


def _validate_vm_list(argv: tuple[str, ...], subscription_id: str) -> None:
    _validate_option_argv(
        argv,
        prefix=("vm", "list", "--show-details", "--only-show-errors", "--output", "json"),
        optional={"--resource-group": _RESOURCE_GROUP},
        required={},
        subscription_id=subscription_id,
    )


def _validate_vm_status(argv: tuple[str, ...], subscription_id: str) -> None:
    _validate_option_argv(
        argv,
        prefix=("vm", "get-instance-view", "--only-show-errors", "--output", "json"),
        optional={},
        required={"--resource-group": _RESOURCE_GROUP, "--name": _RESOURCE_NAME},
        subscription_id=subscription_id,
    )


def _validate_option_argv(
    argv: tuple[str, ...],
    *,
    prefix: tuple[str, ...],
    optional: Mapping[str, re.Pattern[str]],
    required: Mapping[str, re.Pattern[str]],
    subscription_id: str,
) -> None:
    if argv[: len(prefix)] != prefix:
        raise ValueError("Azure command argv does not match the registered command prefix")
    remainder = argv[len(prefix) :]
    if len(remainder) % 2:
        raise ValueError("Azure command options MUST be flag/value pairs")
    seen: dict[str, str] = {}
    for index in range(0, len(remainder), 2):
        flag, value = remainder[index : index + 2]
        if flag in seen:
            raise ValueError("Azure command option appears more than once")
        seen[flag] = value
    allowed = {**optional, **required}
    unknown = sorted(set(seen) - set(allowed) - {"--subscription"})
    if unknown:
        raise ValueError(f"Azure command contains unsupported option(s): {unknown}")
    for flag, pattern in allowed.items():
        option_value = seen.get(flag)
        if flag in required and option_value is None:
            raise ValueError(f"Azure command requires {flag}")
        if option_value is not None and pattern.fullmatch(option_value) is None:
            raise ValueError(f"Azure command argument for {flag} is invalid")
    if seen.get("--subscription") != subscription_id:
        raise ValueError("Azure subscription argument does not match the trusted binding")


_COMMAND_VALIDATORS: Final[dict[str, Callable[[tuple[str, ...], str], None]]] = {
    "azure.resource.list": _validate_resource_list,
    "azure.group.list": _validate_group_list,
    "azure.vm.list": _validate_vm_list,
    "azure.vm.status": _validate_vm_status,
}


def _isolated_env(config_dir: str) -> dict[str, str]:
    return {
        "AZURE_CONFIG_DIR": config_dir,
        "AZURE_CORE_NO_COLOR": "true",
        "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
        "HOME": config_dir,
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


async def _invoke_process(
    argv: tuple[str, ...],
    env: Mapping[str, str],
    timeout_seconds: float,
    max_output_bytes: int,
) -> AzureCliProcessResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
        start_new_session=True,
    )
    stdout_task = asyncio.create_task(_read_bounded(process.stdout, max_output_bytes))
    stderr_task = asyncio.create_task(_read_bounded(process.stderr, max_output_bytes))
    try:
        return_code, stdout, stderr = await asyncio.wait_for(
            asyncio.gather(process.wait(), stdout_task, stderr_task),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise TimeoutError from None
    except _OutputLimitExceededError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise
    except asyncio.CancelledError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        for task in (stdout_task, stderr_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise
    return AzureCliProcessResult(return_code=return_code, stdout=stdout, stderr=stderr)


class _OutputLimitExceededError(RuntimeError):
    pass


async def _read_bounded(stream: asyncio.StreamReader | None, limit: int) -> bytes:
    if stream is None:
        return b""
    output = bytearray()
    while True:
        chunk = await stream.read(8 * 1024)
        if not chunk:
            return bytes(output)
        if len(output) + len(chunk) > limit:
            raise _OutputLimitExceededError()
        output.extend(chunk)


def _failed_receipt(
    plan: CommandPlan,
    result: AzureCliProcessResult,
    started: float,
    label: str,
) -> CommandReceipt:
    detail = _safe_detail(result.stderr)
    return CommandReceipt(
        status=CommandStatus.FAILED,
        receipt_ref=_receipt_ref("azure-command-failed", plan),
        exit_code=result.return_code,
        stderr_tail=f"{label}: {detail}" if detail else label,
        duration_ms=_duration_ms(started),
    )


def _safe_detail(value: bytes) -> str:
    text = value[-4_096:].decode("utf-8", errors="replace")
    lines = [
        "[redacted]" if any(marker in line for marker in _SECRET_MARKERS) else line
        for line in text.splitlines()
    ]
    return " ".join("\n".join(lines).split())[:500]


def _tail(value: bytes) -> str:
    return value[-4_096:].decode("utf-8", errors="replace")


def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _receipt_ref(prefix: str, plan: CommandPlan) -> str:
    payload = f"{plan.command_id}:{plan.command_version}:{plan.idempotency_key}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return f"{prefix}:{plan.command_id}:{digest}"


__all__ = [
    "AzureCliCommandRunner",
    "AzureCliCommandRunnerConfig",
    "AzureCliProcessResult",
]
