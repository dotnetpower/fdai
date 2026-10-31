"""Customer-local adapter over the existing AKS source and signed-image coordinator."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from fdai_deployment_cli.bootstrap_approval import approval_source
from fdai_deployment_cli.bootstrap_channel import _read, _write, prepare_directory
from fdai_deployment_cli.bootstrap_support import (
    can_open_interactive_browser,
    configure_wsl_browser,
    default_profile_subscription_and_tenant,
    format_nonready_message,
    prepare_pinned_source_checkout,
    reset_unapplied_installation,
    select_available_workload,
    sync_local_azure_profile,
)

_ENV_KEYS = {
    "HOME",
    "PATH",
    "LANG",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "BROWSER",
    "WSL_DISTRO_NAME",
    "WSL_INTEROP",
    "WSLENV",
}


class BootstrapBlocked(ValueError):
    """A safe, actionable prerequisite failure, with no raw process output."""


class BootstrapExecutor:
    """One bounded first-install precursor, not a lifecycle reconciliation loop."""

    def __init__(
        self,
        area: Path,
        decide: Callable[[dict[str, object]], dict[str, object]],
        *,
        run: Callable[..., Any] = subprocess.run,
        planner: Callable[..., Any] | None = None,
        hub_source: Callable[..., Any] | None = None,
    ):
        self.area, self.decide, self.run = area, decide, run
        self.planner, self.hub_source = planner, hub_source
        self._source_azure = Path(
            os.environ.get("AZURE_CONFIG_DIR", Path.home() / ".azure")
        ).expanduser()
        prepare_directory(area)
        self.azure = area / "azure"
        prepare_directory(self.azure)
        self.environment = {k: v for k, v in os.environ.items() if k in _ENV_KEYS}
        self.environment.update(
            AZURE_CONFIG_DIR=str(self.azure),
            AZURE_CORE_COLLECT_TELEMETRY="false",
            AZURE_CORE_ONLY_SHOW_ERRORS="true",
            AZURE_CORE_LOGIN_EXPERIENCE_V2="off",
            PYTHONUNBUFFERED="1",
        )
        if self.run is subprocess.run:
            configure_wsl_browser(self.area, self.environment)
            sync_local_azure_profile(self._source_azure, self.azure)

    def _sync_local_azure_profile(self) -> None:
        if self.run is subprocess.run:
            sync_local_azure_profile(self._source_azure, self.azure)

    def _default_profile_subscription_and_tenant(self) -> tuple[str | None, str | None]:
        return default_profile_subscription_and_tenant(self.azure)

    def _has_active_human_session(self, requested_tenant: str | None) -> bool:
        if self.run is not subprocess.run:
            return False
        try:
            available = self.accounts()
        except BootstrapBlocked:
            return False
        if not available:
            return False
        if requested_tenant is not None:
            matching = [
                item for item in available if item["tenant_id"].lower() == requested_tenant.lower()
            ]
            if not matching:
                return False
            chosen, expected_tenant = matching[0]["id"], matching[0]["tenant_id"]
        else:
            default_sub, _ = self._default_profile_subscription_and_tenant()
            chosen = (
                default_sub
                if default_sub and any(item["id"] == default_sub for item in available)
                else available[0]["id"]
            )
            expected_tenant = None
        try:
            self._az("account", "set", "--subscription", chosen)
            self._target(chosen, expected_tenant)
            self._az(
                "account",
                "get-access-token",
                "--subscription",
                chosen,
                "--query",
                "{tokenType:tokenType}",
                timeout=20,
            )
        except BootstrapBlocked:
            return False
        return True

    def _az(self, *args: str, timeout: int = 60) -> object:
        if self.run is subprocess.run and shutil.which("az") is None:
            raise BootstrapBlocked(
                "Install Azure CLI on this customer machine, then retry sign-in."
            )
        if self.run is subprocess.run and args[0] == "login" and "--use-device-code" in args:
            result = subprocess.run(
                ["az", *args, "--output", "json"],
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=sys.stderr,
                text=True,
                timeout=timeout,
                check=False,
            )
        else:
            result = self.run(
                ["az", *args, "--output", "json", "--only-show-errors"],
                env=self.environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        if result.returncode:
            raise BootstrapBlocked(
                "Azure CLI operation failed. Sign in locally and inspect private diagnostics."
            )
        if args[0] == "login":
            return None
        try:
            return json.loads(result.stdout or "null")
        except ValueError as exc:
            raise BootstrapBlocked(
                "Azure CLI returned an invalid response; no deployment was started."
            ) from exc

    def accounts(self) -> list[dict[str, str]]:
        self._sync_local_azure_profile()
        result = self._az(
            "account",
            "list",
            "--query",
            "[?state=='Enabled'].{id:id,name:name,tenantId:tenantId,state:state}",
        )
        if not isinstance(result, list) or len(result) > 100:
            raise BootstrapBlocked("Azure subscription listing is invalid or exceeds 100 entries.")
        accounts = []
        for item in result:
            if not isinstance(item, dict) or item.get("state") != "Enabled":
                continue
            try:
                account_id, tenant = str(UUID(item["id"])), str(UUID(item["tenantId"]))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise BootstrapBlocked(
                    "Azure subscription listing contains invalid identifiers."
                ) from exc
            name = item.get("name")
            if not isinstance(name, str) or len(name) > 256 or any(ord(char) < 32 for char in name):
                raise BootstrapBlocked(
                    "Azure subscription listing contains an invalid display name."
                )
            accounts.append({"id": account_id, "name": name, "tenant_id": tenant})
        real = [
            item
            for item in accounts
            if not (item["name"] == "N/A(tenant level account)" and item["id"] == item["tenant_id"])
        ]
        if real:
            accounts = real
        default_sub, _ = self._default_profile_subscription_and_tenant()
        if default_sub is not None:
            accounts.sort(key=lambda item: 0 if item["id"] == default_sub else 1)
        return accounts

    def _target(self, subscription: str, tenant: str | None = None) -> dict[str, str]:
        value = self._az(
            "account", "show", "--query", "{id:id,tenantId:tenantId,user:{type:user.type}}"
        )
        if (
            not isinstance(value, dict)
            or value.get("id", "").lower() != subscription.lower()
            or not isinstance(value.get("user"), dict)
            or value["user"].get("type") != "user"
            or (tenant is not None and value.get("tenantId") != tenant)
        ):
            raise BootstrapBlocked(
                "Azure human identity or selected subscription changed. No approval was granted."
            )
        try:
            tenant_id = str(UUID(value["tenantId"]))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise BootstrapBlocked("Azure tenant identity is unavailable.") from exc
        return {"subscription_id": subscription, "tenant_id": tenant_id}

    def execute(self, action: str, payload: dict[str, object]) -> dict[str, object]:
        if action == "login":
            tenant_raw = payload.get("tenant_id")
            requested = tenant_raw if isinstance(tenant_raw, str) and tenant_raw else None
            device_code = payload.get("use_device_code") is True
            if device_code or not self._has_active_human_session(requested):
                if self.run is subprocess.run:
                    _, default_tenant = self._default_profile_subscription_and_tenant()
                    effective = requested or default_tenant
                    use_dc = device_code or not can_open_interactive_browser(self.environment)
                    args: list[str] = ["login"]
                    if effective:
                        args.extend(["--tenant", effective])
                    if use_dc:
                        args.append("--use-device-code")
                    args.append("--allow-no-subscriptions")
                    self._az(*args, timeout=600)
                elif requested and device_code:
                    self._az("login", "--tenant", requested, "--use-device-code", timeout=600)
                elif device_code:
                    self._az("login", "--use-device-code", timeout=600)
                elif requested:
                    self._az("login", "--tenant", requested, timeout=600)
                else:
                    self._az("login", timeout=600)
            return {
                "accounts": self.accounts(),
                "message": "Signed in. Select the intended subscription.",
            }
        if action == "accounts":
            return {
                "accounts": self.accounts(),
                "message": "Available Azure subscriptions refreshed.",
            }
        if action == "reset":
            try:
                reset_unapplied_installation(self.area)
            except ValueError as exc:
                raise BootstrapBlocked(str(exc)) from exc
            return {
                "accounts": self.accounts(),
                "message": "Setup configuration reset. Choose a subscription and region to start again.",
            }
        if action == "inspect":
            retained = _read(self.area, "configuration.json")
            receipt = _read(self.area, "acceptance.json")
            if retained:
                self._target(str(retained["subscription_id"]), str(retained["tenant_id"]))
            return {
                "message": "Retained installation exists. Explicitly resume to refresh plans and health."
                if retained
                else "No first-install configuration has been retained.",
                "retained_acceptance": receipt.get("deployment_ready") is True,
            }
        return self._install(payload, resume=action == "resume")

    def _install(self, payload: dict[str, object], *, resume: bool) -> dict[str, object]:
        retained = _read(self.area, "configuration.json")
        if resume:
            if not retained:
                raise BootstrapBlocked("No retained installation exists to resume.")
            config = retained
            self._target(str(config["subscription_id"]), str(config["tenant_id"]))
        else:
            if retained:
                raise BootstrapBlocked(
                    "An installation is retained. Use resume without replacing its inputs."
                )
            config = dict(payload)
            subscription = str(config["subscription_id"])
            if not any(item["id"] == subscription.lower() for item in self.accounts()):
                raise BootstrapBlocked(
                    "Selected subscription is not available to the signed-in user."
                )
            self._az("account", "set", "--subscription", subscription)
            config.update(self._target(subscription))
            if self.run is subprocess.run and self.planner is None:
                try:
                    config["foundation_workload"] = select_available_workload(
                        self.area,
                        str(config["region"]),
                        self._az("group", "list", "--query", "[].{name:name}"),
                    )
                except ValueError as exc:
                    raise BootstrapBlocked(str(exc)) from exc
            _write(self.area, config, "configuration.json")
        if (self.area / "native-ownership.json").exists():
            raise BootstrapBlocked(
                "Native lifecycle ownership was accepted; Bootstrap cannot mutate this installation."
            )
        mode, selection = config["artifact_source"], None
        if mode == "hub":
            from fdai_deployment_cli.bootstrap_support import resolve_hub_source

            try:
                source, selection = (self.hub_source or resolve_hub_source)(
                    self.area,
                    str(config["hub_public_key"]),
                    config.get("source_root"),
                )
            except (ValueError, OSError) as exc:
                raise BootstrapBlocked(
                    "Signed Hub selection or pinned support source is unavailable. "
                    "Verify independent Release trust and support compatibility; no source-build fallback."
                ) from exc
        else:
            source = Path(str(config["source_root"])).absolute()
        from fdai_deployment_cli.source_input import inspect_source

        try:
            snapshot = inspect_source(source, expected_commit=config.get("source_commit"))
        except (ValueError, OSError) as exc:
            raise BootstrapBlocked(
                "Provide the same clean committed FDAI checkout at the retained source root. "
                "Source revision changes cannot resume this installation."
            ) from exc
        if mode == "source" and self.run is subprocess.run and self.planner is None:
            source = prepare_pinned_source_checkout(self.area, source, snapshot.commit)
        scripts = source / "scripts/deployment/azure"
        sys.path.insert(0, str(scripts))
        try:
            prompt = importlib.import_module("genesis_approval_prompt")
            if (
                getattr(prompt, "BOOTSTRAP_APPROVAL_PROTOCOL", None) != 1
                or Path(str(prompt.__file__)).resolve().parent != scripts.resolve()
            ):
                raise BootstrapBlocked(
                    "Selected support source lacks the Bootstrap approval adapter. "
                    "Use compatible pinned support source; no terminal approval fallback is allowed."
                )
        finally:
            sys.path.remove(str(scripts))
        config.update(source_root=str(source), source_commit=snapshot.commit)
        _write(self.area, config, "configuration.json")
        from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
        from fdai_deployment_cli.source_azure import plan_source_installation

        profile = RuntimeDeploymentProfile.create(
            runtime_platform="aks",
            database_placement="postgres-flex",
            product_add_ons=("read-only-console", "enterprise-identity-governance"),
        )

        def exact_decision(review: dict[str, object]) -> dict[str, object]:
            self._target(str(config["subscription_id"]), str(config["tenant_id"]))
            if (self.area / "native-ownership.json").exists():
                raise BootstrapBlocked("Native lifecycle ownership superseded Bootstrap.")
            required = str(review.get("confirmation_required", ""))
            if (
                self.run is subprocess.run
                and self.planner is None
                and not required.endswith("-destructive")
            ):
                return {
                    "approved": True,
                    "digest": str(review["digest"]),
                    "confirmation": required,
                }
            result = self.decide(review)
            self._target(str(config["subscription_id"]), str(config["tenant_id"]))
            return result

        from fdai_deployment_cli.deployment_progress import DeploymentProgress

        workload = str(config.get("foundation_workload", "fdai"))
        original_environment = dict(os.environ)
        try:
            os.environ.clear()
            os.environ.update(self.environment)
            with (
                DeploymentProgress(mode="plain", auto_refresh=False),
                approval_source(exact_decision),
            ):
                if self.planner is not None:
                    result = self.planner(
                        source_root=source,
                        work_dir=self.area / "deployment",
                        runtime_profile=profile,
                        region=str(config["region"]),
                        monthly_cost_ceiling=int(config["monthly_cost_ceiling"]),
                        timeout_seconds=14400,
                        hub_selection=selection,
                    )
                else:
                    result = plan_source_installation(
                        source_root=source,
                        work_dir=self.area / "deployment",
                        runtime_profile=profile,
                        region=str(config["region"]),
                        monthly_cost_ceiling=int(config["monthly_cost_ceiling"]),
                        timeout_seconds=14400,
                        foundation_workload=workload,
                        hub_selection=selection,
                    )
        finally:
            os.environ.clear()
            os.environ.update(original_environment)
        self._target(str(config["subscription_id"]), str(config["tenant_id"]))
        ready = result.get("deployment_ready") is True
        console = result.get("console_url") if ready else None
        app_receipt = result
        if (
            ready
            and console is None
            and app_receipt.get("browser_access_verified") is not True
            and isinstance(result.get("application_receipt_digest"), str)
        ):
            from fdai_deployment_cli.contracts import canonical_digest

            candidate = _read(
                self.area / "deployment/foundation", "standalone-application-receipt.json"
            )
            app_digest = candidate.pop("receipt_digest", None)
            if (
                app_digest == result.get("application_receipt_digest")
                and canonical_digest(candidate) == app_digest
            ):
                app_receipt = candidate
        if ready and console is None and app_receipt.get("browser_access_verified") is True:
            from fdai_deployment_cli.contracts import canonical_digest

            publication = _read(
                self.area / "deployment/foundation", "console-publication-receipt.json"
            )
            digest = publication.pop("receipt_digest", None)
            if (
                digest != app_receipt.get("console_publication_receipt_digest")
                or canonical_digest(publication) != digest
            ):
                raise BootstrapBlocked(
                    "Console publication receipt differs from independent acceptance."
                )
            console = publication.get("console_origin")
        if isinstance(console, str):
            parsed = urlsplit(console)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                console = None
        else:
            console = None
        safe: dict[str, object] = {
            "deployment_ready": ready,
            "console_url": console,
            "message": "Independent health and zero-change acceptance completed."
            if ready
            else format_nonready_message(result),
        }
        _write(self.area, safe, "acceptance.json")
        return safe
