"""Render the isolated namespace and minimum controller observation permissions."""

from __future__ import annotations

import argparse
import re

_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")


def scanner_runtime_resources(
    namespace: str, *, controller_namespace: str, controller_service_account: str
) -> dict[str, object]:
    if any(
        _NAME.fullmatch(value) is None
        for value in (
            namespace,
            controller_namespace,
            controller_service_account,
        )
    ):
        raise ValueError("scanner/controller namespace and service account must be DNS labels")
    if namespace == controller_namespace:
        raise ValueError("credential-bearing controller must be outside the scanner namespace")
    role = "fdai-code-security-controller"
    cluster_role = f"fdai-scanner-observer-{namespace}"
    subject = {
        "kind": "ServiceAccount",
        "name": controller_service_account,
        "namespace": controller_namespace,
    }
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": namespace,
                    "labels": {
                        "pod-security.kubernetes.io/enforce": "restricted",
                        "pod-security.kubernetes.io/enforce-version": "latest",
                    },
                },
            },
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": "fdai-code-security-deny-all", "namespace": namespace},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": [],
                    "egress": [],
                },
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {"name": role, "namespace": namespace},
                "rules": [
                    {
                        "apiGroups": ["batch"],
                        "resources": ["jobs"],
                        "verbs": ["create", "get", "delete"],
                    },
                    {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]},
                    {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]},
                    {
                        "apiGroups": ["networking.k8s.io"],
                        "resources": ["networkpolicies"],
                        "verbs": ["get", "list"],
                    },
                ],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": role, "namespace": namespace},
                "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": role},
                "subjects": [subject],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRole",
                "metadata": {"name": cluster_role},
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["namespaces"],
                        "resourceNames": [namespace],
                        "verbs": ["get"],
                    },
                    {
                        "apiGroups": ["node.k8s.io"],
                        "resources": ["runtimeclasses"],
                        "resourceNames": ["kata-vm-isolation"],
                        "verbs": ["get"],
                    },
                ],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRoleBinding",
                "metadata": {"name": cluster_role},
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": cluster_role,
                },
                "subjects": [subject],
            },
        ],
    }


def add_runtime_render_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser(
        "render-scanner-runtime", help="render the isolated Kata namespace/RBAC"
    )
    parser.add_argument("--scanner-namespace", required=True)
    parser.add_argument("--controller-namespace", required=True)
    parser.add_argument("--controller-service-account", required=True)


def render_scanner_runtime(args: argparse.Namespace) -> dict[str, object]:
    return {
        "ok": True,
        "resources": scanner_runtime_resources(
            args.scanner_namespace,
            controller_namespace=args.controller_namespace,
            controller_service_account=args.controller_service_account,
        ),
    }
