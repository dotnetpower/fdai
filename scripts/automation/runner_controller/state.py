"""Lease-owned controller state. Worker tickets are hashed; registration secrets stay in memory."""

from __future__ import annotations

import copy
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar
from urllib.parse import quote, urlsplit

from scripts.automation.runner_controller.transport import ProviderError, Transport

T = TypeVar("T")


@dataclass
class _PendingTransaction:
    change: Callable[[dict[str, Any]], Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None


class StateStore(Protocol):
    def read(self) -> dict[str, Any]: ...
    def transaction(self, change: Callable[[dict[str, Any]], T]) -> T: ...


class LeaseLostError(RuntimeError):
    """No effect may continue after the controller loses its state lease."""


def _initial() -> dict[str, Any]:
    return {"schema_version": 1, "workers": {}, "low_demand": {}, "deliveries": []}


def _assert_no_secrets(value: object) -> None:
    if isinstance(value, dict):
        forbidden = {
            "pat",
            "access_token",
            "encoded_jit_config",
            "bootstrap_ticket",
            "github_token",
        }
        if forbidden.intersection(value):
            raise ValueError("controller state cannot persist registration or management secrets")
        for item in value.values():
            _assert_no_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_secrets(item)


class BlobState:
    def __init__(
        self,
        account_url: str,
        container: str,
        blob: str,
        token: Callable[[], str],
        transport: Transport | None = None,
    ) -> None:
        parsed = urlsplit(account_url)
        if (
            parsed.scheme != "https"
            or not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", parsed.netloc)
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", container)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", blob)
            or blob in {".", ".."}
        ):
            raise ValueError("state must use one explicit Azure blob with no redirects or queries")
        self.url = f"{account_url.rstrip('/')}/{container}/{quote(blob)}"
        self.token = token
        self.transport = transport or Transport()
        self.lock = threading.RLock()
        self._queue_lock = threading.Lock()
        self._pending: list[_PendingTransaction] = []
        self.lease = str(uuid.uuid4())
        self.etag = ""
        self.renewed = 0.0
        self.alive = False
        self.data: dict[str, Any] = _initial()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token()}",
            "x-ms-version": "2023-11-03",
            "x-ms-date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }

    def open(self) -> None:
        with self.lock:
            try:
                self.transport.request(
                    "PUT",
                    self.url,
                    body=_initial(),
                    accepted=(201,),
                    headers={
                        **self._headers(),
                        "x-ms-blob-type": "BlockBlob",
                        "If-None-Match": "*",
                    },
                )
            except ProviderError as error:
                if error.status not in {409, 412}:
                    raise
            self.transport.request(
                "PUT",
                self.url + "?comp=lease",
                accepted=(201,),
                headers={
                    **self._headers(),
                    "x-ms-lease-action": "acquire",
                    "x-ms-lease-duration": "60",
                    "x-ms-proposed-lease-id": self.lease,
                },
            )
            self.alive = True
            self.renewed = time.monotonic()
            response = self.transport.request("GET", self.url, headers=self._headers())
            if (
                not isinstance(response.data, dict)
                or response.data.get("schema_version") != 1
                or not isinstance(response.data.get("workers"), dict)
                or not isinstance(response.data.get("low_demand"), dict)
            ):
                self.alive = False
                raise LeaseLostError("controller state schema is invalid; refusing effects")
            self.data = response.data
            self.etag = next((v for k, v in response.headers.items() if k.lower() == "etag"), "")
            if not self.etag:
                self.alive = False
                raise LeaseLostError("controller state has no conditional-write identity")

    def renew(self) -> None:
        with self.lock:
            if not self.alive:
                raise LeaseLostError("controller lease is unavailable")
            try:
                self.transport.request(
                    "PUT",
                    self.url + "?comp=lease",
                    accepted=(200,),
                    headers={
                        **self._headers(),
                        "x-ms-lease-action": "renew",
                        "x-ms-lease-id": self.lease,
                    },
                )
            except ProviderError:
                self.alive = False
                raise LeaseLostError("controller lease renewal failed; stopping effects") from None
            self.renewed = time.monotonic()

    def read(self) -> dict[str, Any]:
        with self.lock:
            if not self.alive:
                raise LeaseLostError("controller lease is unavailable")
            return copy.deepcopy(self.data)

    def transaction(self, change: Callable[[dict[str, Any]], T]) -> T:
        item = _PendingTransaction(change)
        with self._queue_lock:
            self._pending.append(item)
        with self.lock:
            if not item.done.is_set():
                with self._queue_lock:
                    batch = list(self._pending)
                    self._pending.clear()
                try:
                    if not self.alive or time.monotonic() - self.renewed >= 50:
                        self.alive = False
                        raise LeaseLostError("controller lease expired before effect reservation")
                    if time.monotonic() - self.renewed >= 15:
                        self.renew()
                except BaseException as exc:
                    for entry in batch:
                        entry.error = exc
                        entry.done.set()
                else:
                    updated = copy.deepcopy(self.data)
                    succeeded: list[_PendingTransaction] = []
                    for entry in batch:
                        candidate = copy.deepcopy(updated)
                        try:
                            value = entry.change(candidate)
                            _assert_no_secrets(candidate)
                        except BaseException as exc:
                            entry.error = exc
                            entry.done.set()
                        else:
                            updated = candidate
                            entry.result = value
                            succeeded.append(entry)
                    if succeeded:
                        try:
                            response = self.transport.request(
                                "PUT",
                                self.url,
                                body=updated,
                                accepted=(201,),
                                headers={
                                    **self._headers(),
                                    "x-ms-blob-type": "BlockBlob",
                                    "x-ms-lease-id": self.lease,
                                    "If-Match": self.etag,
                                },
                            )
                            etag = next(
                                (v for k, v in response.headers.items() if k.lower() == "etag"),
                                "",
                            )
                            if not etag:
                                self.alive = False
                                raise LeaseLostError("controller state write returned no revision")
                            self.etag = etag
                            self.data = updated
                        except ProviderError:
                            self.alive = False
                            loss = LeaseLostError(
                                "controller conditional state write failed; stopping effects"
                            )
                            loss.__cause__ = None
                            for entry in succeeded:
                                entry.error = loss
                                entry.done.set()
                        except BaseException as exc:
                            for entry in succeeded:
                                entry.error = exc
                                entry.done.set()
                        else:
                            for entry in succeeded:
                                entry.done.set()
        if item.error is not None:
            raise item.error
        return item.result  # type: ignore[no-any-return]

    def close(self) -> None:
        with self.lock:
            if self.alive:
                try:
                    self.transport.request(
                        "PUT",
                        self.url + "?comp=lease",
                        accepted=(200,),
                        headers={
                            **self._headers(),
                            "x-ms-lease-action": "release",
                            "x-ms-lease-id": self.lease,
                        },
                    )
                finally:
                    self.alive = False
