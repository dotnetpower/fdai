"""Reconcile owned disposable workers from authoritative jobs and lease-bound capacity evidence."""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from scripts.automation.runner_controller.config import Settings
from scripts.automation.runner_controller.github import GitHubAPI
from scripts.automation.runner_controller.state import StateStore
from scripts.automation.runner_controller.workers import Workers
from scripts.automation.runner_pool_policy import (
    PoolPolicy,
    PoolSnapshot,
    RunnerSnapshot,
    plan_capacity,
)


class Controller:
    def __init__(
        self,
        settings: Settings,
        policies: dict[str, PoolPolicy],
        metadata: dict[str, Any],
        state: StateStore,
        github: GitHubAPI,
        workers: Workers,
    ) -> None:
        self.settings = settings
        self.policies = policies
        self.metadata = metadata
        self.state = state
        self.github = github
        self.workers = workers
        self.last_success: datetime | None = None

    def verify_scope(self) -> None:
        repository_id = self.github.repository_id()
        self.workers.check_ownership()
        owner = hashlib.sha256(
            json.dumps(
                {
                    "repository_id": repository_id,
                    "subscription": self.settings.subscription_id.lower(),
                    "resource_group": self.settings.resource_group.lower(),
                    "jobs": self.settings.jobs,
                    "prefix": self.settings.name_prefix,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

        def bind(data: dict[str, Any]) -> None:
            if data.get("owner") not in {None, owner}:
                raise ValueError("state belongs to a different repository or Azure scope")
            if data.get("owner") is None and data["workers"]:
                raise ValueError("cannot adopt existing workers without an owner binding")
            data["owner"] = owner

        self.state.transaction(bind)
        totals: dict[str, int] = {}
        for item in self.metadata["pools"].values():
            group = item["quota_group"]
            totals[group] = totals.get(group, 0) + item["maximum"] * item["cpu_per_runner"]
        if any(self.settings.cpu_budgets.get(group, -1) < value for group, value in totals.items()):
            raise ValueError("configured pool maxima exceed their approved shared CPU budgets")

    def reconcile(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        registered = self.github.runners()
        jobs = self.github.queued_jobs()
        names = [runner["name"] for runner in registered]
        if len(names) != len(set(names)):
            raise ValueError("duplicate registered runner names; refusing capacity changes")
        by_name = {runner["name"]: runner for runner in registered}
        active_runner_ids = {row["runner_id"] for row in jobs if row["status"] == "in_progress"}
        if self.settings.apply:
            for worker in self.state.read()["workers"].values():
                if worker["status"] == "starting" and not worker.get("provider_ref"):
                    reference = self.workers.recover_reference(worker)
                    if reference:
                        recovered_reference = reference

                        def recovered(
                            data: dict[str, Any],
                            identity: str = worker["id"],
                            ref: str = recovered_reference,
                        ) -> None:
                            data["workers"][identity].update(provider_ref=ref)

                        self.state.transaction(recovered)

        def observe(data: dict[str, Any]) -> None:
            for worker in data["workers"].values():
                if worker["status"] == "terminal":
                    continue
                runner = by_name.get(worker["name"])
                if runner is not None:
                    if not {
                        label.casefold()
                        for label in self.metadata["pools"][worker["pool"]]["labels"]
                    }.issubset({label["name"].casefold() for label in runner["labels"]}):
                        raise ValueError("registered runner labels differ from its reserved pool")
                    worker["registration_id"] = runner["id"]
                    if runner["status"] != "online":
                        if worker["status"] == "idle":
                            worker["status"] = "starting"
                            worker["since"] = now.isoformat()
                        continue
                    busy = runner["busy"] or worker["job_started"]
                    status = "busy" if busy else "idle"
                    if (
                        worker["status"] != status
                        and (worker["status"] != "draining" or busy)
                        and not worker.get("cleanup_requested")
                    ):
                        worker["status"], worker["since"] = status, now.isoformat()
                    if runner["busy"]:
                        worker["job_started"] = True
            data["observed_at"] = now.isoformat()

        self.state.transaction(observe)
        if self.settings.apply:
            for worker in self.state.read()["workers"].values():
                if (
                    worker["status"] == "draining"
                    and not worker.get("cleanup_requested")
                    and not worker["job_started"]
                    and worker["name"] in by_name
                ):
                    self._drain(worker["id"])
        self._retire_finished(by_name, active_runner_ids)
        plans: dict[str, Any] = {}
        for name, policy in self.policies.items():
            if name == "docker" and not self.settings.vm_image_id:
                plans[name] = {"blocked_reason": "docker_image_unavailable"}
                continue
            required = {label.casefold() for label in self.metadata["pools"][name]["labels"]}
            other_labels = {
                label.casefold()
                for other, item in self.metadata["pools"].items()
                if other != name
                for label in item["labels"]
            }
            exclusive = required - other_labels
            queued = sum(
                row["status"] == "queued"
                and {label.casefold() for label in row["labels"]}.issubset(required)
                and bool(exclusive.intersection(label.casefold() for label in row["labels"]))
                for row in jobs
            )
            current = self.state.read()
            owned = [
                worker
                for worker in current["workers"].values()
                if worker["pool"] == name and worker["status"] != "terminal"
            ]
            idle_demand = queued == 0 and not any(worker["status"] == "busy" for worker in owned)

            def demand(
                data: dict[str, Any], *, pool: str = name, quiet: bool = idle_demand
            ) -> None:
                if quiet:
                    data["low_demand"].setdefault(pool, now.isoformat())
                else:
                    data["low_demand"].pop(pool, None)

            self.state.transaction(demand)
            current = self.state.read()
            low_raw = current["low_demand"].get(name)
            low_since = datetime.fromisoformat(low_raw) if low_raw else None
            if low_since and (now - low_since).total_seconds() >= policy.cooldown_seconds:
                policy = replace(
                    policy,
                    warm_idle=self.metadata["pools"][name].get("warm_idle_low", policy.warm_idle),
                )
            expired_idle = [
                worker
                for worker in owned
                if worker["status"] == "idle"
                and (now - datetime.fromisoformat(worker["created_at"])).total_seconds() >= 3600
            ]
            fresh_idle = sum(
                worker["status"] == "idle" and worker not in expired_idle for worker in owned
            )
            if expired_idle:
                if self.settings.apply and fresh_idle >= policy.warm_idle:
                    self._drain(expired_idle[0]["id"])
                    owned = [
                        worker
                        for worker in self.state.read()["workers"].values()
                        if worker["pool"] == name and worker["status"] != "terminal"
                    ]
                else:
                    policy = replace(
                        policy, warm_idle=min(policy.maximum, policy.warm_idle + len(expired_idle))
                    )
            snapshot = PoolSnapshot(
                now,
                queued,
                tuple(
                    RunnerSnapshot(w["id"], w["status"], datetime.fromisoformat(w["since"]))
                    for w in owned
                ),
                low_since,
                True,
            )
            plan = plan_capacity(policy, snapshot, now)
            plans[name] = asdict(plan)
            if not self.settings.apply or plan.blocked_reason:
                continue
            for worker_id in plan.drain_ids:
                self._drain(worker_id)
            for _ in range(plan.start_count):
                self._start(name, now)
        self.last_success = now
        return {"mode": "apply" if self.settings.apply else "observe", "plans": plans}

    def _start(self, pool: str, now: datetime) -> None:
        identity = uuid.uuid4().hex[:20]
        ticket = secrets.token_urlsafe(32)
        record = {
            "id": identity,
            "pool": pool,
            "name": f"{self.settings.name_prefix}-{pool}-{identity}",
            "status": "starting",
            "since": now.isoformat(),
            "created_at": now.isoformat(),
            "ticket_hash": hashlib.sha256(ticket.encode()).hexdigest(),
            "bootstrap_state": "new",
            "registration_id": None,
            "provider_ref": None,
            "job_started": False,
            "listener_exit_code": None,
            "image": (
                self.settings.vm_image_id if pool == "docker" else self.settings.worker_image
            ),
        }

        def reserve(data: dict[str, Any]) -> None:
            count = sum(
                w["pool"] == pool and w["status"] != "terminal" for w in data["workers"].values()
            )
            if count >= self.policies[pool].maximum:
                raise ValueError("pool ceiling changed before start reservation")
            data["workers"][identity] = record

        self.state.transaction(reserve)
        print(
            json.dumps({"event": "worker_start_intent", "pool": pool, "worker": identity}),
            flush=True,
        )
        reference = self.workers.start(record, ticket)
        self.state.transaction(
            lambda data: data["workers"][identity].update(provider_ref=reference)
        )
        print(
            json.dumps({"event": "worker_start_reserved", "pool": pool, "worker": identity}),
            flush=True,
        )

    def _drain(self, identity: str) -> None:
        def reserve(data: dict[str, Any]) -> bool:
            worker = data["workers"][identity]
            if (
                worker["status"] not in {"idle", "draining"}
                or worker["job_started"]
                or not worker["registration_id"]
                or worker.get("cleanup_requested")
            ):
                return False
            worker["status"] = "draining"
            worker["since"] = datetime.now(UTC).isoformat()
            return True

        if not self.state.transaction(reserve):
            return

        def unregister(data: dict[str, Any]) -> None:
            worker = data["workers"][identity]
            if worker["job_started"]:
                worker["status"] = "busy"
            elif not self.github.remove_idle(worker["registration_id"], worker["name"]):
                worker["status"] = "idle"

        self.state.transaction(unregister)

    def _retire_finished(self, registered: dict[str, Any], active: set[int]) -> None:
        if not self.settings.apply:
            return
        for worker in self.state.read()["workers"].values():
            if worker["status"] == "terminal":
                continue
            registration = registered.get(worker["name"])
            if registration is not None:
                if (
                    not registration["busy"]
                    and registration["id"] not in active
                    and self.workers.terminal(worker)
                ):
                    self.github.remove_idle(registration["id"], worker["name"])
                continue
            if worker["registration_id"] in active or not self.workers.terminal(worker):
                continue
            if worker["pool"] == "docker":
                if worker.get("cleanup_requested"):
                    if not self.workers.absent(worker):
                        checked_at = datetime.fromisoformat(worker["cleanup_checked_at"])
                        if (datetime.now(UTC) - checked_at).total_seconds() >= 120:

                            def recheck(data: dict[str, Any], identity: str = worker["id"]) -> None:
                                data["workers"][identity].update(
                                    cleanup_checked_at=datetime.now(UTC).isoformat()
                                )

                            self.state.transaction(recheck)
                            self.workers.cleanup(worker)
                        continue
                else:

                    def cleanup_intent(data: dict[str, Any], identity: str = worker["id"]) -> None:
                        data["workers"][identity].update(
                            cleanup_requested=True,
                            status="draining",
                            cleanup_checked_at=datetime.now(UTC).isoformat(),
                            terminal_observed_at=datetime.now(UTC).isoformat(),
                        )

                    self.state.transaction(cleanup_intent)
                    self.workers.cleanup(worker)
                    continue

            def retired(data: dict[str, Any], identity: str = worker["id"]) -> None:
                data["workers"].pop(identity)
                data["retired_count"] = data.get("retired_count", 0) + 1

            print(
                json.dumps(
                    {
                        "event": "worker_naturally_retired",
                        "worker": worker["id"],
                        "pool": worker["pool"],
                        "listener_exit_code": worker.get("listener_exit_code"),
                    }
                ),
                flush=True,
            )
            self.state.transaction(retired)
