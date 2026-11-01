"""Strict schema and OASIS CSAF 2.0 normalization for MSRC vulnerability advisories."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from fdai.rule_catalog.schema.wara_assessment import (
    ResourceTypeDisposition,
    WaraMappingState,
    canonical_digest,
)
from fdai.shared.contracts.models import Severity

_SHA256 = r"^sha256:[a-f0-9]{64}$"
_CVE_ID = r"^(?:CVE-[0-9]{4}-[0-9]{4,7}|ADV[0-9]{6})$"
_TRACKING_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$"
_PRODUCT_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_IDENTIFIER = r"^[a-z0-9][a-z0-9._:-]{0,255}$"
_KB_ARTICLE = r"^KB[0-9]{6,9}$"
_CVSS_V3_VECTOR = r"^CVSS:3\.[01](/[A-Z]+:[A-Za-z0-9.]+)+$"
_MSRC_HTTPS_PREFIX = "https://msrc.microsoft.com/"
_ALLOWED_REMEDIATION_HOSTS = frozenset(
    {
        "aka.ms",
        "dev.azure.com",
        "docs.azure.cn",
        "docs.microsoft.com",
        "github.com",
        "learn.microsoft.com",
        "msrc.microsoft.com",
        "packages.microsoft.com",
        "portal.msrc.microsoft.com",
        "support.microsoft.com",
    }
)
_MAX_CSAF_BYTES = 2_097_152
_MAX_VULNERABILITIES_PER_ADVISORY = 128
_MAX_PRODUCTS_PER_ADVISORY = 256
_MAX_REMEDIATIONS_PER_VULNERABILITY = 64
_DOTTED_VERSION_RE = re.compile(r"^(?:0|[1-9][0-9]{0,8})(?:\.(?:0|[1-9][0-9]{0,8})){1,7}$")
StrictScalar = StrictStr | StrictBool | StrictInt


class CsafSchemaError(ValueError):
    """Raised when an MSRC CSAF document or crosswalk violates safety invariants."""


def _validate_https_url(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    field_name: str,
    allow_query: bool = False,
) -> None:
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise ValueError(f"{field_name} MUST NOT contain whitespace or control characters")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname not in allowed_hosts
        or not parsed.path.startswith("/")
        or ".." in parsed.path.split("/")
        or (parsed.query and not allow_query)
        or parsed.fragment
    ):
        raise ValueError(f"{field_name} MUST be a clean HTTPS URL on {sorted(allowed_hosts)}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CsafSchemaError(f"duplicate JSON key {key!r} in CSAF artifact")
        result[key] = value
    return result


def _reject_nonfinite_constant(token: str) -> Any:
    raise CsafSchemaError(f"non-finite JSON constant {token!r} is not permitted")


def parse_dotted_version(raw: str) -> tuple[int, ...]:
    """Parse a canonical numeric dotted version into an integer tuple or raise."""

    if not isinstance(raw, str) or _DOTTED_VERSION_RE.fullmatch(raw) is None:
        raise CsafSchemaError(f"version {raw!r} MUST be a canonical numeric dotted version")
    return tuple(int(part) for part in raw.split("."))


def _pad_version(version: tuple[int, ...], length: int) -> tuple[int, ...]:
    return version + (0,) * max(0, length - len(version))


def compare_dotted_versions(left: str, right: str) -> int:
    """Compare two canonical dotted versions numerically (-1, 0, or 1)."""

    left_tuple = parse_dotted_version(left)
    right_tuple = parse_dotted_version(right)
    width = max(len(left_tuple), len(right_tuple))
    padded_left = _pad_version(left_tuple, width)
    padded_right = _pad_version(right_tuple, width)
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


def version_train_prefix(minimum_inclusive: str, ceiling_exclusive: str) -> tuple[int, ...]:
    """Return the shared leading version-train tuple between minimum and ceiling."""

    min_tuple = parse_dotted_version(minimum_inclusive)
    max_tuple = parse_dotted_version(ceiling_exclusive)
    shared: list[int] = []
    for left, right in zip(min_tuple, max_tuple, strict=False):
        if left != right:
            break
        shared.append(left)
    return tuple(shared)


def is_version_in_affected_window(
    observed_version: str,
    *,
    minimum_inclusive: str,
    ceiling_exclusive: str,
) -> bool:
    """Return True when ``observed_version`` lies in ``[minimum_inclusive, ceiling_exclusive)``."""

    if compare_dotted_versions(minimum_inclusive, ceiling_exclusive) >= 0:
        raise CsafSchemaError(
            "affected version window requires minimum_inclusive < ceiling_exclusive"
        )
    return (
        compare_dotted_versions(observed_version, minimum_inclusive) >= 0
        and compare_dotted_versions(observed_version, ceiling_exclusive) < 0
    )


def severity_for_cvss_score(score: float) -> Severity:
    """Map a CVSS v3 base score onto the canonical FDAI Severity band."""

    if not math.isfinite(score) or score < 0.0 or score > 10.0:
        raise CsafSchemaError("CVSS score MUST be a finite number in [0.0, 10.0]")
    if score >= 9.0:
        return Severity.CRITICAL
    if score >= 7.0:
        return Severity.HIGH
    if score >= 4.0:
        return Severity.MEDIUM
    return Severity.LOW


class CsafDisposition(StrEnum):
    EXISTING_RULE = "existing_rule"
    NEW_RULE_CANDIDATE = "new_rule_candidate"
    VERSION_OBSERVATION = "version_observation"
    MANUAL_EVIDENCE = "manual_evidence"
    CONDITIONAL_NOT_APPLICABLE = "conditional_not_applicable"
    AMBIGUOUS_OR_BLOCKED = "ambiguous_or_blocked"


class CsafThreatExploitStatus(StrEnum):
    EXPLOITED = "exploited"
    EXPLOITATION_MORE_LIKELY = "exploitation_more_likely"
    EXPLOITATION_LESS_LIKELY = "exploitation_less_likely"
    EXPLOITATION_UNLIKELY = "exploitation_unlikely"
    PUBLICLY_DISCLOSED = "publicly_disclosed"
    UNPROVEN = "unproven"


class CsafRemediationCategory(StrEnum):
    VENDOR_FIX = "vendor_fix"
    WORKAROUND = "workaround"
    MITIGATION = "mitigation"
    NONE_AVAILABLE = "none_available"


class CsafProductBranch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: Annotated[str, Field(pattern=_PRODUCT_ID)]
    name: Annotated[str, Field(min_length=1, max_length=256)]
    cpe: Annotated[str, Field(min_length=5, max_length=256)] | None = None

    @model_validator(mode="after")
    def validate_product_branch(self) -> CsafProductBranch:
        # C02: Reject control characters or blank names and validate CPE prefix
        if not self.name.strip() or any(ord(ch) < 32 for ch in self.name):
            raise ValueError("CSAF product branch name MUST NOT be blank or contain control chars")
        if self.cpe is not None and (
            any(ch.isspace() or ord(ch) < 32 for ch in self.cpe)
            or not self.cpe.startswith(("cpe:2.3:", "cpe:/"))
        ):
            raise ValueError("CSAF product branch cpe MUST start with 'cpe:2.3:' or 'cpe:/'")
        return self


class CsafRemediationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: CsafRemediationCategory
    product_ids: tuple[Annotated[str, Field(pattern=_PRODUCT_ID)], ...]
    details: Annotated[str, Field(min_length=1, max_length=512)]
    fixed_version: str | None = None
    kb_article: Annotated[str, Field(pattern=_KB_ARTICLE)] | None = None
    workaround_property: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    workaround_expected_value: StrictScalar | None = None
    recommended_action_type: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    url: Annotated[str, Field(min_length=8, max_length=512)] | None = None

    @model_validator(mode="after")
    def validate_remediation(self) -> CsafRemediationRecord:
        if not self.product_ids or self.product_ids != tuple(sorted(set(self.product_ids))):
            raise ValueError("CSAF remediation product_ids MUST be non-empty, unique, and ordered")
        if self.fixed_version is not None:
            parse_dotted_version(self.fixed_version)
        if self.url is not None:
            _validate_https_url(
                self.url,
                allowed_hosts=_ALLOWED_REMEDIATION_HOSTS,
                field_name="CSAF remediation url",
                allow_query=True,
            )
        if (
            self.category is CsafRemediationCategory.VENDOR_FIX
            and self.fixed_version is None
            and self.kb_article is None
        ):
            raise ValueError("vendor_fix remediation requires fixed_version or kb_article")
        # C03: Reject contradictory none_available remediations that claim a fix or action
        if self.category is CsafRemediationCategory.NONE_AVAILABLE and (
            self.fixed_version is not None
            or self.workaround_property is not None
            or self.recommended_action_type is not None
        ):
            raise ValueError(
                "none_available remediation MUST NOT specify fixed_version, workaround, or action"
            )
        if self.category in {
            CsafRemediationCategory.WORKAROUND,
            CsafRemediationCategory.MITIGATION,
        } and (self.workaround_property is None) != (self.workaround_expected_value is None):
            raise ValueError(
                "workaround_property and workaround_expected_value MUST be supplied together"
            )
        return self


class CsafVulnerabilityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cve_id: Annotated[str, Field(pattern=_CVE_ID)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    cvss_base_score: Annotated[float, Field(ge=0.0, le=10.0)]
    cvss_temporal_score: Annotated[float, Field(ge=0.0, le=10.0)] | None = None
    cvss_vector: Annotated[str, Field(pattern=_CVSS_V3_VECTOR)]
    severity: Severity
    exploit_status: CsafThreatExploitStatus
    publicly_disclosed: bool
    known_affected_product_ids: tuple[Annotated[str, Field(pattern=_PRODUCT_ID)], ...]
    fixed_product_ids: tuple[Annotated[str, Field(pattern=_PRODUCT_ID)], ...] = ()
    known_not_affected_product_ids: tuple[Annotated[str, Field(pattern=_PRODUCT_ID)], ...] = ()
    remediations: tuple[CsafRemediationRecord, ...] = ()

    @model_validator(mode="after")
    def validate_vulnerability(self) -> CsafVulnerabilityRecord:
        if not self.known_affected_product_ids:
            raise ValueError("CSAF vulnerability requires at least one known_affected product_id")
        # C01: Validate CVSS vector metric uniqueness and finite temporal score
        vector_metrics = [segment.split(":", 1)[0] for segment in self.cvss_vector.split("/")[1:]]
        if len(vector_metrics) != len(set(vector_metrics)):
            raise ValueError("CSAF cvss_vector MUST NOT contain duplicate metric keys")
        if self.cvss_temporal_score is not None and not math.isfinite(self.cvss_temporal_score):
            raise ValueError("CSAF cvss_temporal_score MUST be a finite number")
        for label, items in (
            ("known_affected_product_ids", self.known_affected_product_ids),
            ("fixed_product_ids", self.fixed_product_ids),
            ("known_not_affected_product_ids", self.known_not_affected_product_ids),
        ):
            if items != tuple(sorted(set(items))):
                raise ValueError(f"{label} MUST be unique and ordered")
        affected = set(self.known_affected_product_ids)
        fixed = set(self.fixed_product_ids)
        unaffected = set(self.known_not_affected_product_ids)
        if (affected & fixed) or (affected & unaffected) or (fixed & unaffected):
            raise ValueError("CSAF product_status sets MUST be mutually disjoint")
        if len(self.remediations) > _MAX_REMEDIATIONS_PER_VULNERABILITY:
            raise ValueError("CSAF vulnerability remediations exceed maximum bound")
        score_severity = severity_for_cvss_score(self.cvss_base_score)
        rank = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
        if rank[self.severity] < rank[score_severity]:
            raise ValueError(
                f"CSAF severity {self.severity.value!r} cannot be lower than CVSS band "
                f"{score_severity.value!r}"
            )
        if self.exploit_status is CsafThreatExploitStatus.EXPLOITED and not self.publicly_disclosed:
            raise ValueError(
                "CSAF vulnerability marked exploited MUST have publicly_disclosed=True"
            )
        for remediation in self.remediations:
            if not set(remediation.product_ids).issubset(affected | fixed):
                raise ValueError(
                    "CSAF remediation product_ids MUST reference known_affected or fixed products"
                )
        return self


class CsafAdvisoryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    csaf_version: Annotated[str, Field(pattern=r"^2\.0$")] = "2.0"
    tracking_id: Annotated[str, Field(pattern=_TRACKING_ID)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    initial_release_date: datetime
    current_release_date: datetime
    revision_count: Annotated[int, Field(ge=1, le=1000)]
    source_url: Annotated[str, Field(min_length=len(_MSRC_HTTPS_PREFIX), max_length=512)]
    document_digest: Annotated[str, Field(pattern=_SHA256)]
    signature_verified: bool
    products: tuple[CsafProductBranch, ...]
    vulnerabilities: tuple[CsafVulnerabilityRecord, ...]

    @field_validator("initial_release_date", "current_release_date")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CSAF advisory timestamps MUST be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_advisory(self) -> CsafAdvisoryDocument:
        _validate_https_url(
            self.source_url,
            allowed_hosts=frozenset({"msrc.microsoft.com"}),
            field_name="CSAF source_url",
        )
        if not self.signature_verified:
            raise ValueError("CSAF advisory MUST have signature_verified=True before admission")
        if self.current_release_date < self.initial_release_date:
            raise ValueError("current_release_date MUST NOT precede initial_release_date")
        if not self.products or len(self.products) > _MAX_PRODUCTS_PER_ADVISORY:
            raise ValueError("CSAF advisory products MUST be non-empty and bounded")
        product_ids = tuple(item.product_id for item in self.products)
        if product_ids != tuple(sorted(set(product_ids))):
            raise ValueError("CSAF advisory products MUST be unique and ordered by product_id")
        if (
            not self.vulnerabilities
            or len(self.vulnerabilities) > _MAX_VULNERABILITIES_PER_ADVISORY
        ):
            raise ValueError("CSAF advisory vulnerabilities MUST be non-empty and bounded")
        cve_ids = tuple(item.cve_id for item in self.vulnerabilities)
        if cve_ids != tuple(sorted(set(cve_ids))):
            raise ValueError("CSAF advisory vulnerabilities MUST be unique and ordered by cve_id")
        declared_products = set(product_ids)
        for vuln in self.vulnerabilities:
            referenced = (
                set(vuln.known_affected_product_ids)
                | set(vuln.fixed_product_ids)
                | set(vuln.known_not_affected_product_ids)
            )
            if not referenced.issubset(declared_products):
                raise ValueError(
                    f"vulnerability {vuln.cve_id} references undeclared product_tree ids"
                )
        return self


class CsafProductCrosswalk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_id: Annotated[str, Field(pattern=_PRODUCT_ID)]
    product_name: Annotated[str, Field(min_length=1, max_length=256)]
    disposition: ResourceTypeDisposition
    canonical_resource_type: str | None
    canonical_resource_types: tuple[str, ...] = ()
    provider_resource_types: tuple[str, ...] = ()
    version_property: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    minimum_affected_version_inclusive: str | None = None
    vulnerable_version_ceiling_exclusive: str | None = None
    freshness_ceiling_seconds: Annotated[int, Field(ge=60, le=31_536_000)] = 86_400
    reviewer: Annotated[str, Field(pattern=_IDENTIFIER)]

    @model_validator(mode="after")
    def validate_product_crosswalk(self) -> CsafProductCrosswalk:
        if self.canonical_resource_types != tuple(sorted(set(self.canonical_resource_types))):
            raise ValueError("canonical_resource_types MUST be unique and ordered")
        if (self.disposition is ResourceTypeDisposition.CANONICAL) != bool(
            self.canonical_resource_types
        ):
            raise ValueError("canonical disposition MUST match canonical_resource_types")
        singleton = (
            self.canonical_resource_types[0] if len(self.canonical_resource_types) == 1 else None
        )
        if self.canonical_resource_type != singleton:
            raise ValueError("canonical_resource_type MUST match singleton canonical candidate")
        if not self.provider_resource_types or self.provider_resource_types != tuple(
            sorted(set(self.provider_resource_types))
        ):
            raise ValueError("provider_resource_types MUST be non-empty, unique, and ordered")
        # C04: Reject blank or case-insensitively duplicated provider_resource_types
        lower_rtypes = [pt.strip().casefold() for pt in self.provider_resource_types]
        if any(not pt or "/" not in pt for pt in lower_rtypes) or len(lower_rtypes) != len(
            set(lower_rtypes)
        ):
            raise ValueError(
                "provider_resource_types MUST be non-blank provider/type strings "
                "without case-fold duplicates"
            )
        if self.disposition is ResourceTypeDisposition.CANONICAL:
            if (
                self.version_property is None
                or self.minimum_affected_version_inclusive is None
                or self.vulnerable_version_ceiling_exclusive is None
            ):
                raise ValueError(
                    "canonical CSAF product crosswalk requires version_property and version window"
                )
            if (
                compare_dotted_versions(
                    self.minimum_affected_version_inclusive,
                    self.vulnerable_version_ceiling_exclusive,
                )
                >= 0
            ):
                raise ValueError(
                    "minimum_affected_version_inclusive MUST be < "
                    "vulnerable_version_ceiling_exclusive"
                )
        return self


class CsafVulnerabilityCrosswalk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cve_id: Annotated[str, Field(pattern=_CVE_ID)]
    advisory_tracking_id: Annotated[str, Field(pattern=_TRACKING_ID)]
    disposition: CsafDisposition
    mapping_state: WaraMappingState
    product_ids: tuple[Annotated[str, Field(pattern=_PRODUCT_ID)], ...]
    existing_rule_id: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    candidate_action_type: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    workaround_property: Annotated[str, Field(pattern=_IDENTIFIER)] | None = None
    workaround_expected_value: StrictScalar | None = None
    blocked_reasons: tuple[Annotated[str, Field(pattern=_IDENTIFIER)], ...] = ()

    @model_validator(mode="after")
    def validate_vulnerability_crosswalk(self) -> CsafVulnerabilityCrosswalk:
        if not self.product_ids or self.product_ids != tuple(sorted(set(self.product_ids))):
            raise ValueError("product_ids MUST be non-empty, unique, and ordered")
        if self.blocked_reasons != tuple(sorted(set(self.blocked_reasons))):
            raise ValueError("blocked_reasons MUST be unique and ordered")
        if self.disposition is CsafDisposition.EXISTING_RULE and self.existing_rule_id is None:
            raise ValueError("existing_rule disposition requires existing_rule_id")
        if self.disposition is CsafDisposition.AMBIGUOUS_OR_BLOCKED and not self.blocked_reasons:
            raise ValueError("ambiguous_or_blocked disposition requires blocked_reasons")
        # C05: Reject unmapped mapping_state when disposition is not ambiguous_or_blocked
        if (
            self.mapping_state is WaraMappingState.UNMAPPED
            and self.disposition is not CsafDisposition.AMBIGUOUS_OR_BLOCKED
        ):
            raise ValueError(
                "unmapped vulnerability crosswalk requires ambiguous_or_blocked disposition"
            )
        if (self.workaround_property is None) != (self.workaround_expected_value is None):
            raise ValueError(
                "workaround_property and workaround_expected_value MUST be supplied together"
            )
        return self


class MsrcCsafCrosswalkCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[str, Field(pattern=r"^1\.0\.0$")] = "1.0.0"
    source_id: Annotated[str, Field(pattern=r"^msrc_csaf$")] = "msrc_csaf"
    source_revision: Annotated[str, Field(pattern=_IDENTIFIER)]
    advisories_digest: Annotated[str, Field(pattern=_SHA256)]
    crosswalk_digest: Annotated[str, Field(pattern=_SHA256)]
    product_mappings: tuple[CsafProductCrosswalk, ...]
    vulnerability_mappings: tuple[CsafVulnerabilityCrosswalk, ...]
    advisories: tuple[CsafAdvisoryDocument, ...]

    @model_validator(mode="after")
    def validate_catalog(self) -> MsrcCsafCrosswalkCatalog:
        prod_ids = tuple(item.product_id for item in self.product_mappings)
        if not prod_ids or prod_ids != tuple(sorted(set(prod_ids))):
            raise ValueError("product_mappings MUST be non-empty, unique, and ordered")
        cve_ids = tuple(item.cve_id for item in self.vulnerability_mappings)
        if not cve_ids or cve_ids != tuple(sorted(set(cve_ids))):
            raise ValueError("vulnerability_mappings MUST be non-empty, unique, and ordered")
        tracking_ids = tuple(item.tracking_id for item in self.advisories)
        if not tracking_ids or tracking_ids != tuple(sorted(set(tracking_ids))):
            raise ValueError("advisories MUST be non-empty, unique, and ordered by tracking_id")
        expected_advisories_digest = canonical_digest(
            [item.model_dump(mode="json") for item in self.advisories]
        )
        if self.advisories_digest != expected_advisories_digest:
            raise ValueError("advisories_digest does not match canonical advisory records")
        advisory_by_tracking = {item.tracking_id: item for item in self.advisories}
        advisory_cves: dict[str, tuple[str, CsafVulnerabilityRecord]] = {}
        advisory_products: set[str] = set()
        for advisory in self.advisories:
            for prod in advisory.products:
                advisory_products.add(prod.product_id)
            for vuln in advisory.vulnerabilities:
                if vuln.cve_id in advisory_cves:
                    raise ValueError(f"duplicate CVE {vuln.cve_id} across advisories")
                advisory_cves[vuln.cve_id] = (advisory.tracking_id, vuln)
        if set(prod_ids) != advisory_products:
            raise ValueError("product_mappings MUST account for every advisory product_id once")
        if set(cve_ids) != set(advisory_cves):
            raise ValueError("vulnerability_mappings MUST account for every advisory CVE once")
        product_by_id = {item.product_id: item for item in self.product_mappings}
        for mapping in self.vulnerability_mappings:
            tracking_id, vuln = advisory_cves[mapping.cve_id]
            if (
                mapping.advisory_tracking_id != tracking_id
                or tracking_id not in advisory_by_tracking
            ):
                raise ValueError(f"advisory_tracking_id mismatch for {mapping.cve_id}")
            if mapping.product_ids != vuln.known_affected_product_ids:
                raise ValueError(
                    f"vulnerability crosswalk product_ids mismatch for {mapping.cve_id}"
                )
            for rem in vuln.remediations:
                if rem.category is CsafRemediationCategory.VENDOR_FIX and rem.fixed_version:
                    for pid in rem.product_ids:
                        pmap = product_by_id[pid]
                        if (
                            pmap.disposition is ResourceTypeDisposition.CANONICAL
                            and pmap.vulnerable_version_ceiling_exclusive != rem.fixed_version
                        ):
                            raise ValueError(
                                f"product {pid} ceiling "
                                f"{pmap.vulnerable_version_ceiling_exclusive!r} "
                                f"does not match advisory vendor_fix {rem.fixed_version!r}"
                            )
            if mapping.workaround_property is not None:
                matched_workaround = any(
                    rem.category
                    in {CsafRemediationCategory.WORKAROUND, CsafRemediationCategory.MITIGATION}
                    and rem.workaround_property == mapping.workaround_property
                    and type(rem.workaround_expected_value)
                    is type(mapping.workaround_expected_value)
                    and rem.workaround_expected_value == mapping.workaround_expected_value
                    for rem in vuln.remediations
                )
                if not matched_workaround:
                    raise ValueError(
                        f"crosswalk workaround for {mapping.cve_id} "
                        "does not match advisory remediations"
                    )
        payload = self.model_dump(mode="json")
        payload.pop("crosswalk_digest", None)
        if self.crosswalk_digest != canonical_digest(payload):
            raise ValueError("crosswalk_digest does not match canonical catalog content")
        return self


def load_msrc_csaf_raw_dict(path: Path) -> dict[str, Any]:
    """Load and assemble a pinned MSRC CSAF crosswalk dictionary (resolving shards when present)."""

    if path.is_symlink() or not path.is_file():
        raise CsafSchemaError("MSRC CSAF crosswalk path MUST be a regular non-symlink file")
    raw_bytes = path.read_bytes()
    if len(raw_bytes) > _MAX_CSAF_BYTES:
        raise CsafSchemaError("MSRC CSAF crosswalk exceeds maximum byte budget")
    try:
        raw: Any = json.loads(
            raw_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CsafSchemaError("MSRC CSAF crosswalk is not valid UTF-8 JSON") from exc
    if not isinstance(raw, dict):
        raise CsafSchemaError("MSRC CSAF crosswalk root MUST be a JSON object")
    shards = raw.get("shards")
    if shards is None:
        return raw
    if not isinstance(shards, list) or not shards:
        raise CsafSchemaError("MSRC CSAF crosswalk shards MUST be a non-empty list")
    assembled_advisories: list[Any] = []
    assembled_vuln_mappings: list[Any] = []
    seen_paths: set[str] = set()
    for idx, shard_ref in enumerate(shards):
        if not isinstance(shard_ref, dict):
            raise CsafSchemaError("MSRC CSAF shard reference MUST be an object")
        rel_path = str(shard_ref.get("path") or "")
        expected_rel_path = f"shards/crosswalk-{idx:02d}.json"
        # C06: Require contiguous ordered shard paths and bounded total records
        if (
            re.fullmatch(r"shards/crosswalk-[0-9]{2}\.json", rel_path) is None
            or rel_path != expected_rel_path
            or rel_path in seen_paths
        ):
            raise CsafSchemaError(f"invalid or non-contiguous MSRC CSAF shard path {rel_path!r}")
        seen_paths.add(rel_path)
        shard_path = path.parent / rel_path
        if shard_path.is_symlink() or not shard_path.is_file():
            raise CsafSchemaError(f"MSRC CSAF shard {rel_path!r} is missing or a symlink")
        shard_bytes = shard_path.read_bytes()
        if len(shard_bytes) > 1_048_576:
            raise CsafSchemaError(f"MSRC CSAF shard {rel_path!r} exceeds 1 MiB ceiling")
        actual_digest = f"sha256:{hashlib.sha256(shard_bytes).hexdigest()}"
        if actual_digest != shard_ref.get("digest"):
            raise CsafSchemaError(f"MSRC CSAF shard digest mismatch for {rel_path!r}")
        shard_obj: Any = json.loads(
            shard_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
        if not isinstance(shard_obj, dict):
            raise CsafSchemaError(f"MSRC CSAF shard {rel_path!r} root MUST be an object")
        shard_advs = shard_obj.get("advisories")
        shard_vmaps = shard_obj.get("vulnerability_mappings")
        if (
            not isinstance(shard_advs, list)
            or not isinstance(shard_vmaps, list)
            or len(shard_advs) != shard_ref.get("advisory_count")
            or len(shard_vmaps) != shard_ref.get("vulnerability_count")
        ):
            raise CsafSchemaError(f"MSRC CSAF shard {rel_path!r} counts do not match manifest")
        assembled_advisories.extend(shard_advs)
        assembled_vuln_mappings.extend(shard_vmaps)
    if (
        not assembled_advisories
        or not assembled_vuln_mappings
        or len(assembled_advisories) > 25_000
        or len(assembled_vuln_mappings) > 25_000
    ):
        raise CsafSchemaError("MSRC CSAF assembled shard counts are empty or exceed ceiling")
    merged = {key: value for key, value in raw.items() if key != "shards"}
    merged["advisories"] = assembled_advisories
    merged["vulnerability_mappings"] = assembled_vuln_mappings
    return merged


def load_msrc_csaf_crosswalk_catalog(path: Path) -> MsrcCsafCrosswalkCatalog:
    """Load and verify a pinned MSRC CSAF crosswalk catalog from disk."""

    return MsrcCsafCrosswalkCatalog.model_validate(load_msrc_csaf_raw_dict(path))


__all__ = [
    "CsafAdvisoryDocument",
    "CsafDisposition",
    "CsafProductBranch",
    "CsafProductCrosswalk",
    "CsafRemediationCategory",
    "CsafRemediationRecord",
    "CsafSchemaError",
    "CsafThreatExploitStatus",
    "CsafVulnerabilityCrosswalk",
    "CsafVulnerabilityRecord",
    "MsrcCsafCrosswalkCatalog",
    "StrictScalar",
    "compare_dotted_versions",
    "is_version_in_affected_window",
    "load_msrc_csaf_crosswalk_catalog",
    "load_msrc_csaf_raw_dict",
    "parse_dotted_version",
    "severity_for_cvss_score",
    "version_train_prefix",
]
