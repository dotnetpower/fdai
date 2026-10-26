"""Kubernetes adapter for workload apply. The only module that imports a Kubernetes client.

It is bound to one kubeconfig context and one namespace and knows only Deployments, Services,
and schema-check Jobs, plus read-only listing of Entity-labelled Deployments and CronJobs.
Server-side apply uses the agent's field manager without forcing conflicts. Connection failures
and server errors are retryable; rejected requests aren't.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from kubernetes import config, dynamic  # type: ignore[import-untyped]
from kubernetes.client import ApiClient, Configuration  # type: ignore[import-untyped]
from kubernetes.client.exceptions import ApiException  # type: ignore[import-untyped]
from urllib3.exceptions import HTTPError

from fdai_lifecycle_agent.reference_state import is_reference_object_name
from fdai_lifecycle_agent.workload import (
    API_VERSIONS,
    ENTITY_LABEL,
    FIELD_MANAGER,
    CreationRejectedError,
    Manifest,
    WorkloadError,
    check_scope,
    is_dns_label,
)

ENROLLMENT_LIST_LIMIT = 100


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

    def adopt_terraform_owned(
        self,
        manifest: Manifest,
        *,
        uid: str,
        resource_version: str,
        dry_run: bool = False,
        before_submit: Callable[[], None] | None = None,
    ) -> Manifest:
        """Transfer only a Terraform-managed spec through one identity-fenced SSA."""

        check_scope((manifest,), self._namespace)
        name = manifest["metadata"]["name"]
        current = self.get(manifest["kind"], name)
        metadata = (current or {}).get("metadata", {})
        if metadata.get("uid") != uid or metadata.get("resourceVersion") != resource_version:
            raise WorkloadError("adoption_resource_drifted")
        managers = {
            str(item.get("manager"))
            for item in metadata.get("managedFields", [])
            if not item.get("subresource")
        }
        if managers != {"Terraform"}:
            raise WorkloadError("adoption_field_manager_conflict")
        body = dict(manifest) | {
            "metadata": dict(manifest["metadata"])
            | {
                "uid": uid,
                "resourceVersion": resource_version,
                "annotations": dict(manifest["metadata"].get("annotations", {}))
                | {"fdai.io/adopted-from": "Terraform"},
            }
        }
        adopted = self._call(
            manifest["kind"],
            lambda client, resource: client.server_side_apply(
                resource,
                body=body,
                namespace=self._namespace,
                field_manager=FIELD_MANAGER,
                force_conflicts=True,
                dry_run="All" if dry_run else None,
                _request_timeout=self._timeout,
            ),
            missing_ok=False,
            before_submit=before_submit,
        )
        result = dict(adopted.to_dict())
        adopted_metadata = result.get("metadata", {})
        if adopted_metadata.get("uid") != uid or not isinstance(
            adopted_metadata.get("resourceVersion"), str
        ):
            raise WorkloadError("adoption_receipt_invalid")
        return result

    def get(self, kind: str, name: str) -> Manifest | None:
        live = self._call(
            kind,
            lambda client, resource: client.get(
                resource, name=name, namespace=self._namespace, _request_timeout=self._timeout
            ),
        )
        return None if live is None else dict(live.to_dict())

    def create(
        self,
        manifest: Manifest,
        *,
        dry_run: bool = False,
        before_submit: Callable[[], None] | None = None,
    ) -> Manifest:
        """POST only: an object appearing after preflight is a conflict, not an adoption."""
        check_scope((manifest,), self._namespace)
        live = self._call(
            manifest["kind"],
            lambda client, resource: client.create(
                resource,
                body=dict(manifest),
                namespace=self._namespace,
                field_manager=FIELD_MANAGER,
                dry_run="All" if dry_run else None,
                _request_timeout=self._timeout,
            ),
            missing_ok=False,
            creating=True,
            before_submit=before_submit,
        )
        return dict(live.to_dict())

    def replace_owned(
        self,
        manifest: Manifest,
        uid: str,
        *,
        dry_run: bool = False,
        before_submit: Callable[[], None] | None = None,
    ) -> None:
        """Atomically test UID/version and replace the spec using existing patch authority."""
        check_scope((manifest,), self._namespace)
        name = manifest["metadata"]["name"]
        current = self.get(manifest["kind"], name)
        metadata = (current or {}).get("metadata", {})
        if metadata.get("uid") != uid or not isinstance(metadata.get("resourceVersion"), str):
            raise WorkloadError("native_resource_identity_changed")
        body = dict(manifest) | {
            "metadata": dict(manifest["metadata"])
            | {"uid": uid, "resourceVersion": metadata["resourceVersion"]}
        }
        if manifest["kind"] == "Service":
            defaults = {
                key: current["spec"][key]
                for key in ("clusterIP", "clusterIPs", "ipFamilies", "ipFamilyPolicy")
                if current is not None and key in current.get("spec", {})
            }
            body["spec"] = defaults | dict(manifest["spec"])
        elif (
            manifest["kind"] == "Deployment"
            and "replicas" not in manifest["spec"]
            and current is not None
            and "replicas" in current.get("spec", {})
        ):
            # An autoscaler owns the replica count; replacing the spec must not reset it.
            body["spec"] = dict(manifest["spec"]) | {"replicas": current["spec"]["replicas"]}
        self._call(
            manifest["kind"],
            lambda client, resource: client.patch(
                resource,
                name=name,
                namespace=self._namespace,
                body=[
                    {"op": "test", "path": "/metadata/uid", "value": uid},
                    {
                        "op": "test",
                        "path": "/metadata/resourceVersion",
                        "value": metadata["resourceVersion"],
                    },
                    {
                        "op": "add",
                        "path": "/metadata/labels",
                        "value": dict(metadata.get("labels", {}))
                        | dict(body["metadata"]["labels"]),
                    },
                    {
                        "op": "add",
                        "path": "/metadata/ownerReferences",
                        "value": body["metadata"].get("ownerReferences", []),
                    },
                    {"op": "replace", "path": "/spec", "value": body["spec"]},
                ],
                content_type="application/json-patch+json",
                field_manager=FIELD_MANAGER,
                dry_run="All" if dry_run else None,
                _request_timeout=self._timeout,
            ),
            missing_ok=False,
            before_submit=before_submit,
        )

    def delete_owned(
        self, kind: str, name: str, uid: str, *, before_submit: Callable[[], None] | None = None
    ) -> None:
        """A same-name replacement cannot satisfy this API-server UID precondition."""
        self._call(
            kind,
            lambda client, resource: client.delete(
                resource,
                name=name,
                namespace=self._namespace,
                body={
                    "apiVersion": "v1",
                    "kind": "DeleteOptions",
                    "preconditions": {"uid": uid},
                },
                _request_timeout=self._timeout,
            ),
            before_submit=before_submit,
        )

    def delete(self, kind: str, name: str) -> None:
        self._call(
            kind,
            lambda client, resource: client.delete(
                resource, name=name, namespace=self._namespace, _request_timeout=self._timeout
            ),
        )

    def read_csi_object(self, kind: str, name: str) -> Manifest | None:
        """Read one exact object through the same SDK transport, without API discovery.

        Fixed read paths avoid unbounded dynamic discovery. Secret, list and value reads
        are unsupported. Every request has the existing mechanical transport timeout.
        """
        paths = {
            "Pod": "/api/v1/namespaces/{namespace}/pods/{name}",
            "SecretProviderClass": "/apis/secrets-store.csi.x-k8s.io/v1/namespaces/"
            "{namespace}/secretproviderclasses/{name}",
            "SecretProviderClassPodStatus": "/apis/secrets-store.csi.x-k8s.io/v1/namespaces/"
            "{namespace}/secretproviderclasspodstatuses/{name}",
        }
        if (
            kind not in paths
            or not is_reference_object_name(name)
            or not is_dns_label(self._namespace)
        ):
            raise WorkloadError("reference_source_outside_scope")
        try:
            live = self._api_client.call_api(
                paths[kind],
                "GET",
                path_params={"namespace": self._namespace, "name": name},
                header_params={"Accept": "application/json"},
                response_types_map={200: "object"},
                auth_settings=["BearerToken"],
                _return_http_data_only=True,
                _request_timeout=self._timeout,
            )
            return dict(live)
        except ApiException as error:
            if error.status == 404:
                return None
            raise WorkloadError("reference_source_unavailable") from error
        except (HTTPError, OSError, TypeError, ValueError) as error:
            raise WorkloadError("reference_source_unavailable") from error

    def list_entity_workloads(self) -> tuple[list[Manifest], list[Manifest]]:
        """List Entity-labelled Deployments and CronJobs in this namespace, read-only.

        Two fixed GETs, each bounded by a page limit and the transport timeout. A further page
        is refused rather than followed, so an oversized namespace cannot be partially enrolled.
        """

        if not is_dns_label(self._namespace):
            raise WorkloadError("enrollment_source_outside_scope")
        paths = (
            "/apis/apps/v1/namespaces/{namespace}/deployments",
            "/apis/batch/v1/namespaces/{namespace}/cronjobs",
        )
        deployments, cronjobs = (self._list_labelled(path) for path in paths)
        return deployments, cronjobs

    def _list_labelled(self, path: str) -> list[Manifest]:
        try:
            live = self._api_client.call_api(
                path,
                "GET",
                path_params={"namespace": self._namespace},
                query_params=[
                    ("labelSelector", ENTITY_LABEL),
                    ("limit", str(ENROLLMENT_LIST_LIMIT)),
                ],
                header_params={"Accept": "application/json"},
                response_types_map={200: "object"},
                auth_settings=["BearerToken"],
                _return_http_data_only=True,
                _request_timeout=self._timeout,
            )
            items = live["items"]
            if live.get("metadata", {}).get("continue") or not isinstance(items, list):
                raise WorkloadError("enrollment_source_too_large")
            return [dict(item) for item in items]
        except WorkloadError:
            raise
        except (ApiException, HTTPError, OSError, KeyError, TypeError, ValueError) as error:
            raise WorkloadError("enrollment_source_unavailable") from error

    def _call(
        self,
        kind: str,
        request: Callable[[Any, Any], Any],
        *,
        missing_ok: bool = True,
        creating: bool = False,
        before_submit: Callable[[], None] | None = None,
    ) -> Any:
        """Run one request; a read/delete ``404`` returns ``None``, not a write success."""

        api_version = API_VERSIONS.get(kind)
        if api_version is None:
            raise WorkloadError("workload_outside_scope")
        try:
            if self._dynamic is None:
                self._dynamic = dynamic.DynamicClient(self._api_client)
            resource = self._dynamic.resources.get(api_version=api_version, kind=kind)
            if before_submit is not None:
                before_submit()
            return request(self._dynamic, resource)
        except ApiException as error:
            if error.status == 404 and missing_ok:
                return None
            if creating and error.status in {400, 401, 403, 404, 405, 409, 413, 415, 422, 429}:
                raise CreationRejectedError("kubernetes_request_rejected") from error
            retryable = error.status is None or error.status >= 500
            raise WorkloadError(
                "kubernetes_unavailable" if retryable else "kubernetes_request_rejected",
                retryable=retryable,
            ) from error
        except (HTTPError, OSError) as error:
            raise WorkloadError("kubernetes_unavailable", retryable=True) from error
