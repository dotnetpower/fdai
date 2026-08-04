"""Bounded CoreDNS NXDOMAIN template candidates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

_ALL_SERVICE_MATCHES: Final = frozenset(
    {r".*\.svc\.cluster\.local\.?$", r"^.*\.svc\.cluster\.local\.?$"}
)


def global_service_nxdomain_findings(
    resources: Sequence[Mapping[str, Any]], *, evidence_complete: bool
) -> tuple[dict[str, Any], ...]:
    """Identify one exact global Service-domain NXDOMAIN template."""

    if not evidence_complete:
        return ()
    findings: list[dict[str, Any]] = []
    for resource in resources:
        if (
            resource.get("kind") != "ConfigMap"
            or resource.get("namespace") != "kube-system"
            or resource.get("name") != "coredns"
            or resource.get("projection_complete") is not True
        ):
            continue
        corefile = resource.get("corefile")
        if not isinstance(corefile, str) or not corefile or len(corefile) > 65_536:
            continue
        matches = [block for block in _blocks(corefile) if _global_nxdomain(block)]
        if len(matches) != 1:
            continue
        findings.append(
            {
                "reason": "coredns_global_service_nxdomain_candidate",
                "resource": {"kind": "ConfigMap", "namespace": "kube-system", "name": "coredns"},
                "dns_scope": "svc.cluster.local",
                "source_paths": ["/data/Corefile"],
                "evidence_strength": "exact_reviewed_template_block",
                "causality": "candidate_only",
                "decision": "hold",
            }
        )
    return tuple(findings)


def _global_nxdomain(block: str) -> bool:
    header = block.splitlines()[0].partition("{")[0].split()
    if not any(token.rstrip(".").casefold() == "svc.cluster.local" for token in header[1:]):
        return False
    if re.search(r"^\s*rcode\s+NXDOMAIN\s*$", block, re.IGNORECASE | re.MULTILINE) is None:
        return False
    matches = re.findall(r'^\s*match\s+"([^"]+)"\s*$', block, re.IGNORECASE | re.MULTILINE)
    return len(matches) == 1 and matches[0] in _ALL_SERVICE_MATCHES


def _blocks(value: str) -> list[str]:
    result: list[str] = []
    lines = value.splitlines()
    index = 0
    while index < len(lines):
        if re.search(r"^\s*template\b", lines[index], re.IGNORECASE) is None:
            index += 1
            continue
        depth = 0
        selected: list[str] = []
        for selected_line in lines[index : index + 256]:
            selected.append(selected_line)
            depth += selected_line.count("{") - selected_line.count("}")
            if depth == 0 and "{" in "\n".join(selected):
                break
        if depth == 0 and selected:
            result.append("\n".join(selected))
        index += max(1, len(selected))
    return result[:32]


__all__ = ["global_service_nxdomain_findings"]
