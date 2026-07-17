"""Chaos Mesh and Litmus resource naming and body builders."""

from __future__ import annotations

from typing import Any

from fdai.core.chaos.scenario_catalog import CatalogEntry


def _cm_pod_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "pod-kill"))
    mode = str(p.get("mode", "one"))
    name = _crd_name(entry)
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  action: {action}
  mode: {mode}
  selector:
    namespaces: [{ctx["workload_namespace"]}]
    labelSelectors:
      app: {ctx["workload_label"]}
"""
    return "PodChaos", body


def _cm_network_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "delay"))
    name = _crd_name(entry)
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: NetworkChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        f"  action: {action}",
        "  mode: one",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
    ]
    if action == "delay":
        lines.extend(
            [
                "  delay:",
                f'    latency: "{p.get("latency_ms", "250")}ms"',
                f'    jitter: "{p.get("jitter_ms", "20")}ms"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "loss":
        lines.extend(
            [
                "  loss:",
                f'    loss: "{p.get("loss_percent", "20")}"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "corrupt":
        lines.extend(
            [
                "  corrupt:",
                f'    corrupt: "{p.get("corrupt_percent", "20")}"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "duplicate":
        lines.extend(
            [
                "  duplicate:",
                f'    duplicate: "{p.get("duplicate_percent", "10")}"',
                f'    correlation: "{p.get("correlation", "50")}"',
            ]
        )
    elif action == "partition":
        lines.append(f"  direction: {p.get('direction', 'both')}")
    elif action == "bandwidth":
        lines.extend(
            [
                "  bandwidth:",
                f'    rate: "{p.get("rate", "1mbps")}"',
                f"    buffer: {p.get('buffer', 10000)}",
                f"    limit: {p.get('limit', 20000)}",
            ]
        )
    return "NetworkChaos", "\n".join(lines) + "\n"


def _cm_http_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    target = str(p.get("target", "Request"))
    port = str(p.get("port", "80"))
    name = _crd_name(entry)
    action = str(p.get("action", "abort"))
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: HTTPChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        "  mode: one",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
        f"  target: {target}",
        f"  port: {port}",
    ]
    if action == "abort":
        lines.append("  abort: true")
    elif action == "delay":
        lines.append(f'  delay: "{p.get("delay", "2s")}"')
    elif action == "replace":
        lines.append("  replace:")
        code = p.get("replace_code")
        if code is not None:
            lines.append(f"    code: {code}")
    return "HTTPChaos", "\n".join(lines) + "\n"


def _cm_stress_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    name = _crd_name(entry)
    stressor = str(p.get("stressor", "cpu"))
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: StressChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        "  mode: one",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
        "  stressors:",
    ]
    if stressor == "cpu":
        lines.extend(
            [
                "    cpu:",
                f"      workers: {p.get('workers', '2')}",
                f"      load: {p.get('load_percent', '90')}",
            ]
        )
    elif stressor == "memory":
        lines.extend(
            [
                "    memory:",
                f"      workers: {p.get('workers', '1')}",
                f'      size: "{p.get("size", "256M")}"',
            ]
        )
    return "StressChaos", "\n".join(lines) + "\n"


def _cm_dns_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "random"))
    scope = str(p.get("scope", "all"))
    patterns = str(p.get("patterns", "*"))
    name = _crd_name(entry)
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: DNSChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  action: {action}
  mode: one
  scope: {scope}
  patterns: ["{patterns}"]
  selector:
    namespaces: [{ctx["workload_namespace"]}]
    labelSelectors:
      app: {ctx["workload_label"]}
"""
    return "DNSChaos", body


def _cm_io_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "latency"))
    percent = str(p.get("percent", "50"))
    name = _crd_name(entry)
    lines = [
        "apiVersion: chaos-mesh.org/v1alpha1",
        "kind: IOChaos",
        "metadata:",
        f"  name: {name}",
        f"  namespace: {ctx['chaos_namespace']}",
        "spec:",
        f"  action: {action}",
        "  mode: one",
        f"  percent: {percent}",
        "  selector:",
        f"    namespaces: [{ctx['workload_namespace']}]",
        "    labelSelectors:",
        f"      app: {ctx['workload_label']}",
    ]
    if action == "latency":
        lines.append(f'  delay: "{p.get("delay_ms", "300")}ms"')
    elif action == "fault":
        errno = p.get("errno", "5")
        lines.append(f"  errno: {errno}")
    return "IOChaos", "\n".join(lines) + "\n"


def _cm_block_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "delay"))
    delay = str(p.get("delay", "300ms"))
    volume = str(p.get("volume", "data"))
    name = _crd_name(entry)
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: BlockChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  action: {action}
  mode: one
  delay:
    latency: "{delay}"
  volumeName: {volume}
"""
    return "BlockChaos", body


def _cm_kernel_chaos_body(entry: CatalogEntry, ctx: dict[str, Any]) -> tuple[str, str]:
    p = entry.spec.get("params") or {}
    action = str(p.get("action", "fail-syscall"))
    name = _crd_name(entry)
    syscall = str(p.get("syscall", "write"))
    errno = str(p.get("errno", "5"))
    body = f"""
apiVersion: chaos-mesh.org/v1alpha1
kind: KernelChaos
metadata:
  name: {name}
  namespace: {ctx["chaos_namespace"]}
spec:
  mode: one
  selector:
    namespaces: [{ctx["workload_namespace"]}]
    labelSelectors:
      app: {ctx["workload_label"]}
  failKernRequest:
    callchain:
      - funcname: "{syscall}"
    failtype: 0
    headers: []
    probability: 100
    times: 1
    action: {action}
    errno: {errno}
"""
    return "KernelChaos", body


_CHAOS_MESH_KINDS: dict[str, Any] = {
    "PodChaos": _cm_pod_chaos_body,
    "NetworkChaos": _cm_network_chaos_body,
    "HTTPChaos": _cm_http_chaos_body,
    "StressChaos": _cm_stress_chaos_body,
    "DNSChaos": _cm_dns_chaos_body,
    "IOChaos": _cm_io_chaos_body,
    "BlockChaos": _cm_block_chaos_body,
    "KernelChaos": _cm_kernel_chaos_body,
}


def _crd_name(entry: CatalogEntry) -> str:
    slug = entry.id.replace(".", "-").replace("_", "-").lower()
    return f"fdai-{slug}"[:40].rstrip("-")


def _litmus_engine_name(entry: CatalogEntry) -> str:
    slug = entry.id.replace(".", "-").replace("_", "-").lower()
    return f"fdai-{slug}"[:50].rstrip("-")


__all__ = [
    "_CHAOS_MESH_KINDS",
    "_cm_block_chaos_body",
    "_cm_dns_chaos_body",
    "_cm_http_chaos_body",
    "_cm_io_chaos_body",
    "_cm_kernel_chaos_body",
    "_cm_network_chaos_body",
    "_cm_pod_chaos_body",
    "_cm_stress_chaos_body",
    "_crd_name",
    "_litmus_engine_name",
]
