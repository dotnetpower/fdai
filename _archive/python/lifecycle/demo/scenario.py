"""Run the demo end to end against a local Hub and the real lifecycle agent.

Each Release step publishes the Release to the channel, recomputes, runs one agent poll, and checks
the result in the Hub's own records. In dry-run mode the agent only admits each Plan, so the
scenario stops after 1.1.0. In apply mode the agent changes the workload, 1.0.0 and 1.1.0 end
`applied`, and 1.2.0 ends `rolled-back` with the Hub holding the Entity.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from lifecycle.demo import catalog
from lifecycle.demo.catalog import ENTITY, INSTALLATION_ID, Layout

from fdai_lifecycle_hub.cli import DATABASE_URL_ENV
from fdai_lifecycle_hub.signing import key_id_for, load_public_key

_HUB = ("fdai-lifecycle-hub", "fdai_lifecycle_hub.cli")
_AGENT = ("fdai-lifecycle-agent", "fdai_lifecycle_agent.cli")
_STARTUP_SECONDS = 15.0


class DemoError(Exception):
    """A step didn't produce what the scenario expects."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Apply:
    """Where the agent applies: one kube context and one dedicated namespace."""

    kube_context: str
    namespace: str
    health_timeout_seconds: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Scenario:
    layout: Layout
    port: int
    apply: Apply | None = None
    pause: bool = False
    say: Callable[[str], None] = print

    @property
    def hub_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def run(self) -> None:
        catalog.prepare(self.layout)
        self._write_local_policy()
        self.hub("migrate")
        self._enroll()
        with self._serve():
            for release in catalog.RELEASES:
                if self.apply is None and release.release_id == "1.2.0":
                    self.say("\nDry run ends here: the 1.2.0 rollback needs --apply.")
                    return
                self._step(release.release_id)
        self.say("\nThe Hub holds core after the failed 1.2.0 and won't plan it again.")

    def hub(self, *args: str, echo: bool = True) -> dict[str, Any]:
        record: dict[str, Any] = json.loads(self._run(_HUB, args, echo=echo))
        return record

    def _enroll(self) -> None:
        self._title("Enroll the installation and manage its core Entity")
        layout = self.layout
        pending = self.hub(
            "dev-enroll", str(layout.enrollment), "--key", str(layout.key("installation"))
        )
        key_id = pending["installation_key_id"]
        self.hub(
            "approve",
            INSTALLATION_ID,
            "--approver",
            "demo-approver",
            "--installation-key-id",
            key_id,
        )
        self.hub(
            "record-ownership",
            INSTALLATION_ID,
            ENTITY,
            str(layout.ownership),
            "--operator",
            "demo-operator",
        )
        self.hub(
            "manage", INSTALLATION_ID, ENTITY, str(layout.settings), "--operator", "demo-operator"
        )

    def _step(self, release_id: str) -> None:
        self._title(f"Release {release_id}: {catalog.RELEASES_BY_ID[release_id].image}")
        self.say(f"channel: {catalog.publish(self.layout, release_id)}")
        issued = self._recompute()
        _expect(issued, outcome="issued", target=release_id)
        plan_id = issued["plan_id"]
        self._run(_AGENT, self._poll_args())

        shown = self.hub("show", INSTALLATION_ID, echo=False)
        outcomes = [r["outcome"] for r in shown["reports"] if r["plan_id"] == plan_id]
        self.say(f"reports for {plan_id}: {outcomes}")
        if self.apply is None:
            _require(outcomes == ["dry-run-admitted"], f"expected one dry-run report: {outcomes}")
            return
        failed = release_id == "1.2.0"
        final = "rolled-back" if failed else "applied"
        _require(
            outcomes == ["apply-started", final], f"expected apply-started, {final}: {outcomes}"
        )
        after = self._recompute()
        if not failed:
            _expect(after, outcome="up-to-date")
            return
        _expect(after, outcome="waiting", target=release_id)
        held = self.hub("show", INSTALLATION_ID, echo=False)
        self.say(f"suppressions: {held['suppressions']}")
        _require(held["plan"] is None, "the Hub still serves a Plan")
        _require(
            any(
                (s["scope"], s["origin"], s["failed_plan_id"])
                == (f"entity:{ENTITY}", "failure", plan_id)
                for s in held["suppressions"]
            ),
            "no failure suppression for the rolled-back Plan",
        )

    def _recompute(self) -> dict[str, Any]:
        record = self.hub(
            "recompute",
            INSTALLATION_ID,
            *("--catalog", str(self.layout.catalog)),
            *("--key", str(self.layout.key("hub"))),
            echo=False,
        )
        blocks = {
            c["release_id"]: [b["reason_code"] for b in c["blocks"]] for c in record["checks"]
        }
        self.say(f"recompute: {record['outcome']} target={record.get('target')} checks={blocks}")
        return record

    def _poll_args(self) -> list[str]:
        layout = self.layout
        args = [
            "poll-once",
            *("--hub-url", self.hub_url),
            *("--installation-id", INSTALLATION_ID),
            *("--state-dir", str(layout.agent_state)),
            *("--hub-public-key", str(layout.public_key("hub"))),
            *("--hub-key-id", key_id_for(load_public_key(layout.public_key("hub")))),
            *("--hub-key-epoch", "1"),
            *("--fencing-generation", "1"),
            *("--release-public-key", str(layout.public_key("release"))),
            *("--configuration-public-key", str(layout.public_key("configuration"))),
            *("--inputs-dir", str(layout.inputs)),
            *("--current-state", str(layout.current_state)),
            *("--local-policy", str(layout.local_policy)),
        ]
        if self.apply is not None:
            args += [
                "--apply",
                *("--kube-context", self.apply.kube_context),
                *("--namespace", self.apply.namespace),
                *("--health-timeout-seconds", str(self.apply.health_timeout_seconds)),
            ]
        return args

    def _write_local_policy(self) -> None:
        policy = catalog.local_policy(apply=self.apply is not None)
        self.layout.local_policy.write_text(json.dumps(policy, indent=2) + "\n")

    def _run(self, program: tuple[str, str], args: Sequence[str], *, echo: bool = True) -> str:
        name, module = program
        self.say(f"$ {shlex.join([name, *args])}")
        result = subprocess.run(  # noqa: S603 - fixed module, arguments built above.
            [sys.executable, "-m", module, *args],
            env=self._env(),
            capture_output=True,
            text=True,
            check=False,
        )
        if echo and result.stdout.strip():
            self.say(result.stdout.strip())
        if result.returncode != 0:
            raise DemoError(f"{name} exited {result.returncode}: {result.stderr.strip()}")
        return result.stdout

    def _env(self) -> dict[str, str]:
        return os.environ | {DATABASE_URL_ENV: self.layout.database_url}

    @contextmanager
    def _serve(self) -> Iterator[None]:
        if _healthy(self.hub_url):
            raise DemoError(f"something already answers on {self.hub_url}; choose another --port")
        log = (self.layout.root / "hub.log").open("w")
        server = subprocess.Popen(  # noqa: S603 - fixed module and port.
            [sys.executable, "-m", _HUB[1], "serve", "--port", str(self.port)],
            env=self._env(),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + _STARTUP_SECONDS
            while not _healthy(self.hub_url):
                if server.poll() is not None or time.monotonic() > deadline:
                    raise DemoError(f"the Hub API did not start; see {log.name}")
                time.sleep(0.2)
            self.say(f"Hub API on {self.hub_url} (log: {log.name})")
            yield
        finally:
            server.terminate()
            server.wait(timeout=10)
            log.close()

    def _title(self, text: str) -> None:
        if self.pause:
            input("\n[Enter] next step ")
        self.say(f"\n== {text} ==")


def _healthy(url: str) -> bool:
    try:
        return httpx.get(f"{url}/healthz", timeout=1.0).status_code == 200
    except httpx.TransportError:
        return False


def _expect(record: dict[str, Any], *, outcome: str, target: str | None = None) -> None:
    actual = (record["outcome"], record.get("target"))
    _require(
        actual[0] == outcome and (target is None or actual[1] == target),
        f"expected {outcome} {target or ''}, got {actual}",
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DemoError(message)
