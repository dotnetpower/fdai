"""Single-use short-lived registration; workers never receive the repository PAT."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

from scripts.automation.runner_controller.github import GitHubAPI
from scripts.automation.runner_controller.state import StateStore


class Broker:
    def __init__(self, state: StateStore, github: GitHubAPI, pools: dict[str, Any]) -> None:
        self.state = state
        self.github = github
        self.pools = pools

    @staticmethod
    def authenticate(data: dict[str, Any], worker_id: str, ticket: str) -> dict[str, Any]:
        worker = data["workers"].get(worker_id)
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        if (
            not isinstance(worker, dict)
            or worker["status"] == "terminal"
            or not hmac.compare_digest(worker["ticket_hash"], digest)
        ):
            raise ValueError("invalid or retired worker ticket")
        return worker

    def bootstrap(self, worker_id: str, ticket: str, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)

        def claim(data: dict[str, Any]) -> dict[str, Any]:
            worker = self.authenticate(data, worker_id, ticket)
            age = (now - datetime.fromisoformat(worker["created_at"])).total_seconds()
            if not 0 <= age <= 300 or worker["bootstrap_state"] != "new":
                raise ValueError("bootstrap ticket is expired or already claimed")
            worker["bootstrap_state"] = "claimed"
            worker["claimed_at"] = now.isoformat()
            return dict(worker)

        # Conditional state is committed before the provider call. Concurrent/replayed requests
        # cannot mint two registrations, and an ambiguous response is never blindly retried.
        worker = self.state.transaction(claim)
        runner_id, encoded = self.github.jit(worker["name"], self.pools[worker["pool"]]["labels"])

        def delivered(data: dict[str, Any]) -> None:
            current = self.authenticate(data, worker_id, ticket)
            if current["bootstrap_state"] != "claimed":
                raise ValueError("bootstrap state changed during registration")
            current["registration_id"] = runner_id
            current["bootstrap_state"] = "delivered"

        self.state.transaction(delivered)
        return encoded

    def lifecycle(self, event: str, payload: dict[str, Any]) -> None:
        if event not in {"registered", "started", "finished"}:
            raise ValueError("unknown worker lifecycle event")
        worker_id, ticket = payload["worker_id"], payload["ticket"]
        if not isinstance(worker_id, str) or not isinstance(ticket, str):
            raise ValueError("worker identity and ticket must be strings")

        def update(data: dict[str, Any]) -> None:
            worker = self.authenticate(data, worker_id, ticket)
            if worker.get("cleanup_requested") and event != "finished":
                raise ValueError("worker has already entered terminal resource cleanup")
            if worker["bootstrap_state"] not in {"delivered", "acked"}:
                raise ValueError("worker lifecycle preceded registration delivery")
            now = datetime.now(UTC).isoformat()
            if event == "registered":
                worker["bootstrap_state"] = "acked"
            elif event == "started":
                worker["job_started"] = True
                worker["status"] = "busy"
                worker["since"] = now
            else:
                code = payload["exit_code"]
                if type(code) is not int or not 0 <= code <= 255:
                    raise ValueError("listener exit code must be an integer from 0 to 255")
                if worker.get("listener_exit_code") not in {None, code}:
                    raise ValueError("listener terminal report conflicts with retained evidence")
                worker["listener_exit_code"] = code
                worker["finished_at"] = now

        self.state.transaction(update)
