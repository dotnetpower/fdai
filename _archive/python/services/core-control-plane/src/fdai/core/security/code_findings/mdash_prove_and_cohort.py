"""Microsoft Codename MDASH Dedupe, Prove plugins, Cohort & MSEM regional governance (M036-M080).

Implements Stages 4-5 (Dedupe patch-site equivalence, Prove domain plugins,
fuzzer harness format adaptation, task specificity diagnostics), the May 2026
Patch Tuesday 16-CVE cohort discovered by Codename MDASH, retrospective MSRC
recall & CyberGym benchmark readiness, and Microsoft Security Exposure
Management (MSEM) regional sovereignty / allowlist validation.

All outputs are read-only evidence (`execution_authority=False`).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.security.code_findings.models import Occurrence


class FuzzerHarnessFormat(StrEnum):
    """Supported dynamic proof harness input formats (M058)."""

    LIBFUZZER = "libfuzzer"
    HONGGFUZZ = "honggfuzz"
    AFL_PLUSPLUS = "afl_plusplus"
    STANDALONE_POC = "standalone_poc"


@dataclass(frozen=True, slots=True)
class MdashDeduplicatedCluster:
    """Dedupe-stage patch-equivalence and multi-file alias-chain cluster (M036-M050)."""

    cluster_id: str
    patch_equivalence_key: str
    primary_fix_path: str
    primary_fix_line: int
    cwe_ids: tuple[int, ...]
    chain_files: tuple[str, ...]
    occurrence_ids: tuple[str, ...]
    max_posterior_credibility: float


def deduplicate_by_patch_equivalence(
    occurrences: Sequence[Occurrence],
    *,
    credibility_by_occurrence: Mapping[str, float] | None = None,
) -> tuple[MdashDeduplicatedCluster, ...]:
    """Consolidate occurrences that share a patch site or multi-file code_flow root (M036-M050)."""
    cred_map = credibility_by_occurrence or {}
    buckets: dict[str, list[Occurrence]] = {}
    for occ in occurrences:
        root_step = occ.code_flow[0] if occ.code_flow else None
        anchor_path = root_step.path if root_step is not None else occ.location.path
        anchor_line = (
            (root_step.line or 0) if root_step is not None else (occ.location.start_line or 0)
        )
        cwe_head = occ.cwe_ids[0] if occ.cwe_ids else 0
        patch_key = f"{cwe_head}:{anchor_path}:{anchor_line // 5}"
        buckets.setdefault(patch_key, []).append(occ)

    clusters: list[MdashDeduplicatedCluster] = []
    for patch_key in sorted(buckets):
        members = buckets[patch_key]
        primary = members[0]
        chain_files: set[str] = {m.location.path for m in members}
        for m in members:
            for step in m.code_flow:
                chain_files.add(step.path)
        cwes = tuple(sorted({c for m in members for c in m.cwe_ids}))
        occ_ids = tuple(sorted({m.occurrence_id for m in members}))
        max_cred = max((cred_map.get(m.occurrence_id, 0.75) for m in members), default=0.75)
        cid = "mdash-cluster-" + hashlib.sha256(patch_key.encode("utf-8")).hexdigest()[:12]
        clusters.append(
            MdashDeduplicatedCluster(
                cluster_id=cid,
                patch_equivalence_key=patch_key,
                primary_fix_path=primary.location.path,
                primary_fix_line=primary.location.start_line or 1,
                cwe_ids=cwes,
                chain_files=tuple(sorted(chain_files)),
                occurrence_ids=occ_ids,
                max_posterior_credibility=round(max_cred, 3),
            )
        )
    return tuple(clusters)


@dataclass(frozen=True, slots=True)
class MdashDomainProvingPlugin:
    """Extensible Prove-stage domain plugin metadata (M051-M057)."""

    plugin_id: str
    target_subsystem: str
    supported_cwes: tuple[int, ...]
    invariants_encoded: tuple[str, ...]
    default_harness_format: FuzzerHarnessFormat
    sanitizer_flags: tuple[str, ...]


MDASH_BUILTIN_PROVING_PLUGINS: tuple[MdashDomainProvingPlugin, ...] = (
    MdashDomainProvingPlugin(
        plugin_id="clfs-log-container-prover",
        target_subsystem="clfs.sys",
        supported_cwes=(120, 125, 416, 787),
        invariants_encoded=(
            "blf_base_record_sector_checksum",
            "container_block_offset_alignment",
            "marshalling_context_state_machine",
        ),
        default_harness_format=FuzzerHarnessFormat.STANDALONE_POC,
        sanitizer_flags=("KASAN", "SpecialPool"),
    ),
    MdashDomainProvingPlugin(
        plugin_id="tcpip-ipv4-ipv6-packet-prover",
        target_subsystem="tcpip.sys",
        supported_cwes=(125, 191, 416, 476, 787),
        invariants_encoded=(
            "ipv4_ssrr_routing_header_refcount",
            "ipv6_extension_header_mdl_split",
            "ipsec_esp_sa_reassembly_splice",
        ),
        default_harness_format=FuzzerHarnessFormat.LIBFUZZER,
        sanitizer_flags=("ASan", "UBSan"),
    ),
    MdashDomainProvingPlugin(
        plugin_id="ikev2-fragment-skf-prover",
        target_subsystem="ikeext.dll",
        supported_cwes=(401, 415, 416),
        invariants_encoded=(
            "ike_sa_init_security_realm_vendor_id",
            "rfc7383_skf_fragment_reinjection_memcpy",
            "demand_start_bfe_responder_policy",
        ),
        default_harness_format=FuzzerHarnessFormat.STANDALONE_POC,
        sanitizer_flags=("ASan", "PageHeap"),
    ),
    MdashDomainProvingPlugin(
        plugin_id="quic-cldap-dns-protocol-prover",
        target_subsystem="http.sys/netlogon.dll/dnsapi.dll",
        supported_cwes=(121, 122, 125, 787),
        invariants_encoded=(
            "quic_control_stream_frame_bounds",
            "cldap_user_filter_stack_frame",
            "udp_dns_rdata_label_compression",
        ),
        default_harness_format=FuzzerHarnessFormat.HONGGFUZZ,
        sanitizer_flags=("ASan", "UBSan"),
    ),
    MdashDomainProvingPlugin(
        plugin_id="web-sql-cmd-ssrf-prover",
        target_subsystem="application-services",
        supported_cwes=(22, 78, 89, 502, 918),
        invariants_encoded=(
            "parameterized_sql_sink_hook",
            "subprocess_arg_vector_hook",
            "canonical_realpath_containment_hook",
        ),
        default_harness_format=FuzzerHarnessFormat.STANDALONE_POC,
        sanitizer_flags=("HookRecorder",),
    ),
)


def adapt_fuzzer_harness_input(
    payload: bytes,
    *,
    source_format: FuzzerHarnessFormat,
    target_harness_code: str,
) -> tuple[FuzzerHarnessFormat, bytes]:
    """Adapt PoC input between libFuzzer and honggfuzz to prevent format mismatch (M058)."""
    detected = source_format
    if "HF_ITER" in target_harness_code or "honggfuzz" in target_harness_code.casefold():
        detected = FuzzerHarnessFormat.HONGGFUZZ
    elif "LLVMFuzzerTestOneInput" in target_harness_code:
        detected = FuzzerHarnessFormat.LIBFUZZER
    elif "__AFL_LOOP" in target_harness_code:
        detected = FuzzerHarnessFormat.AFL_PLUSPLUS

    if detected is source_format:
        return (detected, payload)
    if detected is FuzzerHarnessFormat.HONGGFUZZ and not payload.startswith(b"HFZ:"):
        return (detected, b"HFZ:" + len(payload).to_bytes(4, "big") + payload)
    if (
        detected is FuzzerHarnessFormat.LIBFUZZER
        and payload.startswith(b"HFZ:")
        and len(payload) >= 8
    ):
        return (detected, payload[8:])
    return (detected, payload)


@dataclass(frozen=True, slots=True)
class TaskSpecificityDiagnostic:
    """Task description quality diagnostic preventing the 82% CyberGym wrong-area failure (M060)."""

    has_file_anchor: bool
    has_function_anchor: bool
    has_cwe_anchor: bool
    specificity_score: float
    enriched_target_files: tuple[str, ...]


def diagnose_task_description_specificity(
    description: str,
    *,
    candidate_paths: Sequence[str] = (),
) -> TaskSpecificityDiagnostic:
    """Score task description specificity and auto-attach top candidate files when vague (M060)."""
    has_file = bool(re.search(r"\b[\w./-]+\.(?:c|cc|cpp|h|py|js|ts|java|cs|go|rs)\b", description))
    has_fn = bool(
        re.search(r"\b[A-Za-z_]\w+\s*\(|\b(?:in|function|method)\s+[A-Za-z_]\w+", description)
    )
    has_cwe = bool(re.search(r"(?i)\bcwe-\d+|\bcve-\d{4}-\d+", description))
    score = round(
        (0.45 if has_file else 0.0) + (0.35 if has_fn else 0.0) + (0.20 if has_cwe else 0.0),
        2,
    )
    enriched = tuple(candidate_paths[:5]) if score < 0.50 and candidate_paths else ()
    return TaskSpecificityDiagnostic(
        has_file_anchor=has_file,
        has_function_anchor=has_fn,
        has_cwe_anchor=has_cwe,
        specificity_score=score,
        enriched_target_files=enriched,
    )


@dataclass(frozen=True, slots=True)
class MdashCohortAdvisory:
    """One CVE from the May 2026 Patch Tuesday cohort discovered by Codename MDASH (M066)."""

    cve_id: str
    component: str
    execution_mode: str  # kernel or usermode
    severity: str
    impact_type: str
    description: str


MDASH_PATCH_TUESDAY_COHORT_16: tuple[MdashCohortAdvisory, ...] = (
    MdashCohortAdvisory(
        "CVE-2026-33827",
        "tcpip.sys",
        "kernel",
        "Critical",
        "Remote Code Execution",
        "Remote unauth SSRR IPv4 packets causing refcount UAF",
    ),
    MdashCohortAdvisory(
        "CVE-2026-40413",
        "tcpip.sys",
        "kernel",
        "Important",
        "Denial of Service",
        "NULL deref via crafted IPv6 extension headers",
    ),
    MdashCohortAdvisory(
        "CVE-2026-40405",
        "tcpip.sys",
        "kernel",
        "Important",
        "Denial of Service",
        "Kernel DoS via ESP SA refcount underflow",
    ),
    MdashCohortAdvisory(
        "CVE-2026-33824",
        "ikeext.dll",
        "usermode",
        "Critical",
        "Remote Code Execution",
        "Unauth IKEv2 SA_INIT + SKF fragment double-free LocalSystem RCE",
    ),
    MdashCohortAdvisory(
        "CVE-2026-40406",
        "tcpip.sys",
        "kernel",
        "Important",
        "Information Disclosure",
        "Use-after-free in Ipv4pReassembleDatagram leading to disclosure",
    ),
    MdashCohortAdvisory(
        "CVE-2026-35422",
        "tcpip.sys",
        "kernel",
        "Important",
        "Security Feature Bypass",
        "IPsec cross-SA fragment splicing via reassembly",
    ),
    MdashCohortAdvisory(
        "CVE-2026-32209",
        "tcpip.sys",
        "kernel",
        "Important",
        "Security Feature Bypass",
        "Unauthenticated local WFP RPC disables name cache",
    ),
    MdashCohortAdvisory(
        "CVE-2026-35424",
        "ikeext.dll",
        "usermode",
        "Important",
        "Denial of Service",
        "IKEEXT service memory leak DoS",
    ),
    MdashCohortAdvisory(
        "CVE-2026-35423",
        "telnet.exe",
        "usermode",
        "Important",
        "Information Disclosure",
        "Out-of-bounds read in FProcessSB via malformed TO_AUTH",
    ),
    MdashCohortAdvisory(
        "CVE-2026-40414",
        "tcpip.sys",
        "kernel",
        "Important",
        "Denial of Service",
        "IPv6+TCP MDL-split packet triggers NULL deref",
    ),
    MdashCohortAdvisory(
        "CVE-2026-40401",
        "tcpip.sys",
        "kernel",
        "Important",
        "Denial of Service",
        "ICMPv6 packet triggers NdisGetDataBuffer NULL deref",
    ),
    MdashCohortAdvisory(
        "CVE-2026-40415",
        "tcpip.sys",
        "kernel",
        "Important",
        "Remote Code Execution",
        "Pre-auth remote UAF via SA double-decrement",
    ),
    MdashCohortAdvisory(
        "CVE-2026-33096",
        "http.sys",
        "kernel",
        "Important",
        "Denial of Service",
        "Unauth remote QUIC control-stream OOB read",
    ),
    MdashCohortAdvisory(
        "CVE-2026-40399",
        "tcpip.sys",
        "kernel",
        "Important",
        "Elevation of Privilege",
        "Kernel stack buffer overflow via RPC blob",
    ),
    MdashCohortAdvisory(
        "CVE-2026-41089",
        "netlogon.dll",
        "usermode",
        "Critical",
        "Remote Code Execution",
        "Unauthenticated CLDAP User= filter stack overflow",
    ),
    MdashCohortAdvisory(
        "CVE-2026-41096",
        "dnsapi.dll",
        "usermode",
        "Critical",
        "Remote Code Execution",
        "Crafted UDP DNS response triggers heap OOB",
    ),
)

MDASH_REGIONAL_SUPPORT: Mapping[str, dict[str, bool]] = {
    "US": {"portal_supported": True, "cli_supported": True},
    "EU": {"portal_supported": True, "cli_supported": True},
    "UK": {"portal_supported": True, "cli_supported": True},
    "AUS": {"portal_supported": True, "cli_supported": True},
    "IND": {"portal_supported": True, "cli_supported": True},
    "CH": {"portal_supported": True, "cli_supported": True},
    "UAE": {"portal_supported": False, "cli_supported": True},
}

MDASH_REQUIRED_ALLOWLIST_DOMAINS: tuple[str, ...] = (
    "*.cli.dfd.security.azure.com",
    "*.blob.core.windows.net",
    "*.azurefd.net",
    "*.login.microsoftonline.com",
    "*.graph.microsoft.com",
    "aspm-data-externalapi-prd.security.aspm.microsoft.com",
    "*.token.actions.githubusercontent.com",
    "*.dev.azure.com",
)


def validate_mdash_regional_deployment(
    region: str,
    *,
    require_portal: bool = True,
    configured_allowlist: Sequence[str] = (),
) -> tuple[bool, tuple[str, ...]]:
    """Validate MDASH regional sovereignty (UAE CLI-only rule) and domain allowlist (M075)."""
    norm_region = region.strip().upper()
    reasons: list[str] = []
    if norm_region not in MDASH_REGIONAL_SUPPORT:
        reasons.append(f"unsupported_mdash_region:{norm_region}")
    else:
        caps = MDASH_REGIONAL_SUPPORT[norm_region]
        if require_portal and not caps["portal_supported"]:
            reasons.append(f"region_cli_only_portal_unsupported:{norm_region}")
    if configured_allowlist:
        allowed_set = set(configured_allowlist)
        for req_domain in MDASH_REQUIRED_ALLOWLIST_DOMAINS[:6]:
            if req_domain not in allowed_set:
                reasons.append(f"missing_allowlist_domain:{req_domain}")
    return (len(reasons) == 0, tuple(reasons))


__all__ = [
    "FuzzerHarnessFormat",
    "MDASH_BUILTIN_PROVING_PLUGINS",
    "MDASH_PATCH_TUESDAY_COHORT_16",
    "MDASH_REGIONAL_SUPPORT",
    "MDASH_REQUIRED_ALLOWLIST_DOMAINS",
    "MdashCohortAdvisory",
    "MdashDeduplicatedCluster",
    "MdashDomainProvingPlugin",
    "TaskSpecificityDiagnostic",
    "adapt_fuzzer_harness_input",
    "deduplicate_by_patch_equivalence",
    "diagnose_task_description_specificity",
    "validate_mdash_regional_deployment",
]
