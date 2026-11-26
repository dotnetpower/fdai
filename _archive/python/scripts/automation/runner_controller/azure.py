"""Scope-locked Azure management and platform managed-identity clients."""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from .transport import DEFAULT_ACCEPTED, HttpResponse, ProviderError, Transport

_BASE = "https://management.azure.com"
_VERSION = "2024-03-01"
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SEGMENT = re.compile(r"[A-Za-z0-9_.()-]{1,260}")
_API_VERSION = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-preview)?")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"})
_IDENTITY_RESOURCES = frozenset({"https://management.azure.com/", "https://storage.azure.com/"})
_MAX_PAGES = 100


def _segment(value: str) -> str:
    if not _SEGMENT.fullmatch(value) or value in {".", ".."}:
        raise ProviderError("scope")
    return value


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderError("invalid_response")
    return value


def _token(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(ord(char) < 33 or ord(char) > 126 for char in value)
    ):
        raise ProviderError("identity")
    return value


class AzureAPI:
    def __init__(
        self,
        subscription_id: str,
        resource_group: str,
        token_provider: Callable[[], str],
        transport: Transport | None = None,
    ) -> None:
        if (
            not _GUID.fullmatch(subscription_id)
            or not _SEGMENT.fullmatch(resource_group)
            or resource_group in {".", ".."}
            or len(resource_group) > 90
            or resource_group.endswith(".")
        ):
            raise ProviderError("scope")
        self._root = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        self._token_provider = token_provider
        self._transport = transport if transport is not None else Transport()

    def __repr__(self) -> str:
        return "AzureAPI()"

    def _path(self, resource_path: str) -> str:
        """Reject encoded aliases and normalize nothing across the scope boundary."""
        parts = resource_path.split("/")
        if (
            not resource_path.startswith("/")
            or any(not _SEGMENT.fullmatch(part) or part in {".", ".."} for part in parts[1:])
            or not (
                resource_path.lower() == self._root.lower()
                or resource_path.lower().startswith(self._root.lower() + "/")
            )
        ):
            raise ProviderError("scope")
        return resource_path

    def request(
        self,
        method: str,
        resource_path: str,
        *,
        body: Any = None,
        api_version: str = _VERSION,
        accepted: tuple[int, ...] = DEFAULT_ACCEPTED,
    ) -> HttpResponse:
        path = self._path(resource_path)
        if method not in _METHODS or not _API_VERSION.fullmatch(api_version):
            raise ProviderError("invalid_request")
        return self._request(
            method, _BASE + path + "?" + urlencode({"api-version": api_version}), body, accepted
        )

    def _request(self, method: str, url: str, body: Any, accepted: tuple[int, ...]) -> HttpResponse:
        try:
            token = _token(self._token_provider())
        except Exception:
            raise ProviderError("identity") from None
        return self._transport.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            body=body,
            accepted=accepted,
        )

    def _job_path(self, job_name: str) -> str:
        return f"{self._root}/providers/Microsoft.App/jobs/{_segment(job_name)}"

    def start_container(self, job_name: str, template: dict[str, Any]) -> str:
        if not isinstance(template, dict):
            raise ProviderError("invalid_request")
        data = _object(
            self.request("POST", self._job_path(job_name) + "/start", body=template).data
        )
        name = data.get("name")
        if not isinstance(name, str):
            raise ProviderError("invalid_response")
        return _segment(name)

    def container_executions(self, job_name: str) -> list[dict[str, Any]]:
        path = self._job_path(job_name) + "/executions"
        response = self.request("GET", path)
        executions: list[dict[str, Any]] = []
        visited: set[str] = set()
        for page in range(_MAX_PAGES):
            data = _object(response.data)
            values = data.get("value")
            if not isinstance(values, list):
                raise ProviderError("invalid_response")
            executions.extend(_object(value) for value in values)
            next_link = data.get("nextLink")
            if next_link is None or next_link == "":
                return executions
            if not isinstance(next_link, str):
                raise ProviderError("scope")
            url = self._continuation(next_link, path)
            if url in visited:
                raise ProviderError("pagination_limit")
            if page + 1 == _MAX_PAGES:
                raise ProviderError("pagination_limit")
            visited.add(url)
            response = self._request("GET", url, None, (200,))
        raise ProviderError("pagination_limit")

    def _continuation(self, link: str, expected_path: str) -> str:
        try:
            parsed = urlsplit(link)
            if (
                parsed.scheme != "https"
                or parsed.netloc.lower() != "management.azure.com"
                or parsed.fragment
                or any(ord(char) < 33 or ord(char) == 127 for char in link)
                or self._path(parsed.path).lower() != expected_path.lower()
            ):
                raise ProviderError("scope")
            query = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            versions = [value for key, value in query if key == "api-version"]
            if versions != [_VERSION] or len({key for key, _ in query}) != len(query):
                raise ProviderError("scope")
            return _BASE + parsed.path + "?" + urlencode(query)
        except ValueError:
            raise ProviderError("scope") from None

    def container_execution(self, job_name: str, execution_name: str) -> dict[str, Any]:
        return self.get_resource(
            self._job_path(job_name) + "/executions/" + _segment(execution_name)
        )

    def stop_container(self, job_name: str, execution_name: str) -> None:
        """Send stop only after the caller has independently established safe termination."""
        self.request(
            "POST",
            self._job_path(job_name) + "/executions/" + _segment(execution_name) + "/stop",
        )

    def put_resource(
        self, path: str, body: dict[str, Any], api_version: str = _VERSION
    ) -> dict[str, Any]:
        return _object(self.request("PUT", path, body=body, api_version=api_version).data)

    def get_resource(self, path: str, api_version: str = _VERSION) -> dict[str, Any]:
        return _object(self.request("GET", path, api_version=api_version, accepted=(200,)).data)

    def delete_resource(self, path: str, api_version: str = _VERSION) -> None:
        self.request("DELETE", path, api_version=api_version, accepted=(200, 202, 204, 404))


class ManagedIdentityToken:
    """Acquire ARM or Storage tokens from the platform endpoint; never invoke Azure CLI."""

    def __init__(
        self,
        resource: str = "https://management.azure.com/",
        transport: Transport | None = None,
    ) -> None:
        if resource not in _IDENTITY_RESOURCES:
            raise ProviderError("identity")
        self._resource = resource
        self._transport = transport if transport is not None else Transport()
        self._lock = threading.Lock()
        self._cached: tuple[str, str, str, float, str] | None = None

    def __repr__(self) -> str:
        return "ManagedIdentityToken()"

    def __call__(self) -> str:
        endpoint = os.environ.get("IDENTITY_ENDPOINT", "")
        header = os.environ.get("IDENTITY_HEADER", "")
        client_id = os.environ.get("AZURE_CLIENT_ID", "")
        try:
            parsed = urlsplit(endpoint)
            hostname = parsed.hostname
            if hostname == "localhost":
                private = True
            else:
                address = ipaddress.ip_address(hostname or "")
                private = (
                    address.is_loopback
                    or address.is_link_local
                    or (address.is_private and not address.is_reserved)
                ) and not (address.is_unspecified or address.is_multicast)
            if (
                not private
                or parsed.scheme not in {"http", "https"}
                or parsed.username is not None
                or parsed.password is not None
                or "?" in endpoint
                or "#" in endpoint
                or not parsed.path.startswith("/")
                or any(
                    not _SEGMENT.fullmatch(part) or part in {".", ".."}
                    for part in parsed.path.split("/")[1:]
                )
                or any(ord(char) < 33 or ord(char) == 127 for char in endpoint)
                or parsed.port == 0
                or (client_id and not _GUID.fullmatch(client_id))
            ):
                raise ProviderError("identity")
            header = _token(header)
        except ValueError:
            raise ProviderError("identity") from None
        with self._lock:
            now = time.time()
            if (
                self._cached is not None
                and self._cached[:3] == (endpoint, header, client_id)
                and self._cached[3] - now > 120
            ):
                return self._cached[4]
            params = {"api-version": "2019-08-01", "resource": self._resource}
            if client_id:
                params["client_id"] = client_id
            query = urlencode(params)
            response = self._transport.request(
                "GET",
                endpoint + "?" + query,
                headers={"X-IDENTITY-HEADER": header},
                accepted=(200,),
            )
            data = _object(response.data)
            token = _token(data.get("access_token"))
            raw_expiry = data.get("expires_on")
            if isinstance(raw_expiry, (int, str)) and str(raw_expiry).isdigit():
                self._cached = (endpoint, header, client_id, float(raw_expiry), token)
            return token
