"""Kubernetes adapter for workload apply. The only module that imports a Kubernetes client.

It is bound to one kubeconfig context and one namespace and knows only Deployments, Services,
and schema-check Jobs. Server-side apply uses the agent's field manager without forcing
conflicts. Connection failures and server errors are retryable; rejected requests aren't.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kubernetes import config, dynamic  # type: ignore[import-untyped]
from kubernetes.client import ApiClient, Configuration  # type: ignore[import-untyped]
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]
from urllib3.exceptions import HTTPError

from fdai_lifecycle_agent.workload import (
    API_VERSIONS,
    FIELD_MANAGER,
    Manifest,
    WorkloadError,
    check_scope,
)


class KubernetesCluster:
    """``Cluster`` over the Kubernetes dynamic client. Discovery runs on the first call.

    Raises ``ValueError`` when the kubeconfig context can't be loaded.
    """

    def __init__(
        self,
        *,
        context: str | None = None,
        namespace: str,
        in_cluster: bool = False,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        if in_cluster == bool(context):
            raise ValueError("Select exactly one kubeconfig context or in-cluster authentication.")
        try:
            if in_cluster:
                configuration = Configuration()
                config.load_incluster_config(client_configuration=configuration)
                self._api_client = ApiClient(configuration=configuration)
            else:
                self._api_client = config.new_client_from_config(context=context)
        except (config.ConfigException, OSError) as error:
            raise ValueError(
                f"Kubernetes authentication is unusable: {type(error).__name__}"
            ) from error
        self._namespace = namespace
        self._timeout = request_timeout_seconds
        self._dynamic: Any = None

    def apply(self, manifest: Manifest, *, dry_run: bool = False) -> None:
        check_scope((manifest,), self._namespace)
        self._call(
            manifest["kind"],
            lambda client, resource: client.server_side_apply(
                resource,
                body=dict(manifest),
                namespace=self._namespace,
                field_manager=FIELD_MANAGER,
                force_conflicts=False,
                dry_run="All" if dry_run else None,
                _request_timeout=self._timeout,
            ),
            missing_ok=False,
        )

    def get(self, kind: str, name: str) -> Manifest | None:
        live = self._call(
            kind,
            lambda client, resource: client.get(
                resource, name=name, namespace=self._namespace, _request_timeout=self._timeout
            ),
        )
        return None if live is None else dict(live.to_dict())

    def delete(self, kind: str, name: str) -> None:
        self._call(
            kind,
            lambda client, resource: client.delete(
                resource, name=name, namespace=self._namespace, _request_timeout=self._timeout
            ),
        )

    def _call(
        self, kind: str, request: Callable[[Any, Any], Any], *, missing_ok: bool = True
    ) -> Any:
        """Run one request; a read/delete ``404`` returns ``None``, not a write success."""

        api_version = API_VERSIONS.get(kind)
        if api_version is None:
            raise WorkloadError("workload_outside_scope")
        try:
            if self._dynamic is None:
                self._dynamic = dynamic.DynamicClient(self._api_client)
            resource = self._dynamic.resources.get(api_version=api_version, kind=kind)
            return request(self._dynamic, resource)
        except ApiException as error:
            if error.status == 404 and missing_ok:
                return None
            retryable = error.status is None or error.status >= 500
            raise WorkloadError(
                "kubernetes_unavailable" if retryable else "kubernetes_request_rejected",
                retryable=retryable,
            ) from error
        except (HTTPError, OSError) as error:
            raise WorkloadError("kubernetes_unavailable", retryable=True) from error
