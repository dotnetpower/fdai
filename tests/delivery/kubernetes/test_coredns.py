"""CoreDNS global NXDOMAIN candidate tests."""

from __future__ import annotations

from fdai.delivery.kubernetes.coredns import global_service_nxdomain_findings


def test_global_coredns_nxdomain_requires_exact_reviewed_template() -> None:
    finding = global_service_nxdomain_findings([_resource(_corefile())], evidence_complete=True)[0]
    assert finding["dns_scope"] == "svc.cluster.local"
    assert finding["decision"] == "hold"


def test_global_coredns_nxdomain_abstains_on_truncated_or_specific_service() -> None:
    specific = _corefile().replace(
        r".*\.svc\.cluster\.local\.?$", r"^api\.shop\.svc\.cluster\.local\.$"
    )
    assert not global_service_nxdomain_findings([_resource(_corefile())], evidence_complete=False)
    assert not global_service_nxdomain_findings([_resource(specific)], evidence_complete=True)


def test_global_coredns_nxdomain_abstains_on_ambiguous_or_non_nxdomain_blocks() -> None:
    ambiguous = f"{_corefile()}\n{_corefile()}"
    success = _corefile().replace("rcode NXDOMAIN", "rcode NOERROR")
    assert not global_service_nxdomain_findings([_resource(ambiguous)], evidence_complete=True)
    assert not global_service_nxdomain_findings([_resource(success)], evidence_complete=True)


def test_global_coredns_nxdomain_rejects_malformed_or_oversized_input() -> None:
    assert not global_service_nxdomain_findings([_resource("template {")], evidence_complete=True)
    assert not global_service_nxdomain_findings([_resource("x" * 65_537)], evidence_complete=True)


def test_global_coredns_nxdomain_is_metamorphic_to_resource_order() -> None:
    noise = {"kind": "Service", "namespace": "example-app", "name": "api"}
    expected = global_service_nxdomain_findings(
        [_resource(_corefile()), noise], evidence_complete=True
    )
    assert (
        global_service_nxdomain_findings([noise, _resource(_corefile())], evidence_complete=True)
        == expected
    )


def _resource(corefile: str) -> dict[str, object]:
    return {
        "kind": "ConfigMap",
        "namespace": "kube-system",
        "name": "coredns",
        "projection_complete": True,
        "corefile": corefile,
    }


def _corefile() -> str:
    return """.:53 {
  template ANY ANY svc.cluster.local {
    match ".*\\.svc\\.cluster\\.local\\.?$"
    rcode NXDOMAIN
  }
}
"""
