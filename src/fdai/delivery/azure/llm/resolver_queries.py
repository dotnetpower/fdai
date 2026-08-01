"""Azure CLI-backed adapters for the LLM bootstrap resolver.

The pure resolver in :mod:`fdai.rule_catalog.schema.llm_resolver` takes
three tiny Protocol-shaped queries (catalog / permission / quota) so it
stays SDK-free and easy to test. The offline path feeds those queries
from JSON fixtures via
:mod:`fdai.rule_catalog.schema.llm_resolver_cli`; this module is the
real-world path - each Protocol is implemented as a small ``az`` CLI
subprocess wrapper, matching the pattern in
:mod:`fdai.delivery.azure.dev_inventory` and
:mod:`fdai.delivery.azure.dev_workload_identity`.

Auth: whatever principal ``az login`` currently holds. Set
``AZURE_CONFIG_DIR`` when a fork keeps a customer profile separate
from the default one (see the customer-tenant note in the repo README).

Failure policy: **fail closed**. Every query surface raises a typed
:class:`AzureCliResolverError` on any transport / parsing failure so
the resolver's environmental-failure paths degrade the affected
capability to ``hil-only``. We never fabricate a positive answer.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from urllib.parse import quote, urlencode, urlparse

from fdai.rule_catalog.schema.llm_resolver import (
    CatalogQuery,
    PermissionQuery,
    ProvisionedCapacityQuery,
    QuotaQuery,
)

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_TPM_PER_USAGE_UNIT = 1_000


class AzureCliResolverError(RuntimeError):
    """Raised when an ``az`` subprocess fails or returns unusable JSON.

    Callers treat this as an environmental failure and let the resolver
    degrade the affected capability to ``hil-only`` per the standard
    fail-closed contract.
    """


def _run_az(argv: Sequence[str], *, timeout: float) -> str:
    """Run ``az`` and return stdout; raise :class:`AzureCliResolverError` on any failure."""
    try:
        proc = subprocess.run(  # noqa: S603 - CLI adapter, timeout enforced
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AzureCliResolverError(
            f"'{argv[0]}' not found on PATH; install the Azure CLI"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AzureCliResolverError(f"'{' '.join(argv)}' timed out after {timeout}s") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise AzureCliResolverError(
            f"az CLI exited with code {proc.returncode}: "
            f"{stderr[:400] if stderr else '(no stderr)'}"
        )
    return proc.stdout or ""


# ---------------------------------------------------------------------------
# CatalogQuery - which model families are in a region
# ---------------------------------------------------------------------------


class AzureCliCatalogQuery(CatalogQuery):
    """Fetch the OpenAI model catalog for a region via ``az cognitiveservices model list``.

    The result is memoised per region so a single resolver run does not
    re-invoke ``az`` once per capability. Memoisation is per-instance,
    not global, so tests can construct fresh instances at will.
    """

    def __init__(
        self,
        *,
        executable: str = "az",
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._executable = executable
        self._timeout = timeout
        self._cache: dict[str, set[str]] = {}

    def families_in_region(self, region: str) -> set[str]:
        if region in self._cache:
            return set(self._cache[region])
        argv = [
            self._executable,
            "cognitiveservices",
            "model",
            "list",
            "-l",
            region,
            "--query",
            "[?kind=='OpenAI'].model.name",
            "-o",
            "json",
        ]
        stdout = _run_az(argv, timeout=self._timeout)
        try:
            names = json.loads(stdout or "[]")
        except json.JSONDecodeError as exc:
            raise AzureCliResolverError("az CLI returned non-JSON for catalog list") from exc
        if not isinstance(names, list):
            raise AzureCliResolverError("catalog query MUST return a JSON array")
        families = {str(n) for n in names if isinstance(n, str)}
        self._cache[region] = families
        return set(families)


# ---------------------------------------------------------------------------
# PermissionQuery - does a principal hold the Contributor role
# ---------------------------------------------------------------------------


class AzureCliPermissionQuery(PermissionQuery):
    """Check ``Cognitive Services Contributor`` on a subscription scope.

    The check is a single ``az role assignment list`` call filtered by
    principal object id and role name. Any non-empty result means the
    role is held (either directly or through a group membership that
    ``az`` has already expanded).
    """

    _ROLE_NAME: str = "Cognitive Services Contributor"

    def __init__(
        self,
        *,
        executable: str = "az",
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._executable = executable
        self._timeout = timeout

    def principal_has_cognitive_services_contributor(
        self, *, subscription_id: str, principal_object_id: str
    ) -> bool:
        argv = [
            self._executable,
            "role",
            "assignment",
            "list",
            "--scope",
            f"/subscriptions/{subscription_id}",
            "--assignee-object-id",
            principal_object_id,
            "--role",
            self._ROLE_NAME,
            "-o",
            "json",
        ]
        stdout = _run_az(argv, timeout=self._timeout)
        try:
            payload = json.loads(stdout or "[]")
        except json.JSONDecodeError as exc:
            raise AzureCliResolverError(
                "az CLI returned non-JSON for role assignment list"
            ) from exc
        if not isinstance(payload, list):
            raise AzureCliResolverError("role assignment list MUST return a JSON array")
        return len(payload) > 0


# ---------------------------------------------------------------------------
# QuotaQuery - available capacity per (region, publisher, family)
# ---------------------------------------------------------------------------


class AzureCliQuotaQuery(QuotaQuery):
    """Per-region Azure OpenAI usage snapshot from ``az cognitiveservices usage list``.

    The az command returns per-quota-metric usage in thousands of TPM::

        [
          {
            "currentValue": 40,
            "limit": 240,
            "name": {"value": "OpenAI.Standard.gpt-4o-mini"}
          },
          ...
        ]

    The ``name.value`` shape is a dotted quota-id whose LAST segment is
    the model family. This adapter matches runtime inference tiers only,
    converts ``limit - currentValue`` to TPM, and excludes batch,
    fine-tune, developer, and provisioned quota. Any un-parseable entry
    contributes zero.

    Publisher is not part of the quota id, so this adapter treats
    ``(region, family)`` as the lookup key and ignores the publisher
    argument (Azure quotas are family-scoped, not publisher-scoped).
    Fail-closed: on subprocess or JSON errors we raise, which lets the
    resolver degrade the affected capability to ``hil-only``.
    """

    def __init__(
        self,
        *,
        executable: str = "az",
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._executable = executable
        self._timeout = timeout
        self._cache: dict[str, dict[str, int]] = {}

    def available_capacity_tpm(self, *, region: str, publisher: str, family: str) -> int:
        del publisher  # Azure quotas are family-scoped, not publisher-scoped.
        by_family = self._cache.get(region)
        if by_family is None:
            by_family = self._load_region(region)
            self._cache[region] = by_family
        # Azure quota metric names historically use dashed families
        # (``gpt-4o-mini``); newer families carry an internal dot
        # (``gpt-5.4-mini``). Look up both forms so the resolver stays
        # consistent regardless of which convention Azure lands on for
        # the model of the day.
        return max((by_family.get(alias, 0) for alias in _family_aliases(family)), default=0)

    def _load_region(self, region: str) -> dict[str, int]:
        argv = [
            self._executable,
            "cognitiveservices",
            "usage",
            "list",
            "-l",
            region,
            "-o",
            "json",
        ]
        stdout = _run_az(argv, timeout=self._timeout)
        try:
            payload = json.loads(stdout or "[]")
        except json.JSONDecodeError as exc:
            raise AzureCliResolverError("az CLI returned non-JSON for usage list") from exc
        if not isinstance(payload, list):
            raise AzureCliResolverError("usage list MUST return a JSON array")
        out: dict[str, int] = {}
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if isinstance(name, dict):
                name_value = name.get("value")
            else:
                name_value = name
            if not isinstance(name_value, str) or not name_value:
                continue
            if not _is_interactive_tpm_quota(name_value):
                continue
            limit = _as_int(entry.get("limit"))
            current = _as_int(entry.get("currentValue"))
            if limit is None:
                continue
            available = max(0, limit - (current or 0)) * _TPM_PER_USAGE_UNIT
            # Index the entry under every family-shaped key we can pull
            # from the quota metric name. Azure historically uses
            # ``OpenAI.Standard.<family>`` where <family> may itself
            # contain dots (``gpt-5.4-mini``), so we register both the
            # last dot-segment AND the suffix after any known tier
            # marker.
            for key in _family_keys(name_value):
                if available > out.get(key, 0):
                    out[key] = available
        return out


class AzureCliProvisionedCapacityQuery(ProvisionedCapacityQuery):
    """Query live deployable PTUs from the Azure Model Capacities REST API."""

    _API_VERSION = "2024-10-01"

    def __init__(
        self,
        *,
        subscription_id: str,
        executable: str = "az",
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
        max_pages: int = 5,
    ) -> None:
        if not subscription_id.strip() or max_pages < 1:
            raise ValueError("PTU capacity query subscription and page cap MUST be valid")
        self._subscription_id = subscription_id
        self._executable = executable
        self._timeout = timeout
        self._max_pages = max_pages
        self._versions: dict[tuple[str, str], str] = {}
        self._capacity: dict[tuple[str, str, str], int] = {}

    def available_capacity_ptu(
        self,
        *,
        region: str,
        publisher: str,
        family: str,
        sku: str,
    ) -> int:
        if publisher.casefold() != "openai":
            return 0
        key = (region.casefold(), family, sku)
        if key not in self._capacity:
            version = self._model_version(region=region, family=family)
            self._capacity[key] = self._load_capacity(
                region=region,
                family=family,
                version=version,
                sku=sku,
            )
        return self._capacity[key]

    def _model_version(self, *, region: str, family: str) -> str:
        key = (region.casefold(), family)
        cached = self._versions.get(key)
        if cached is not None:
            return cached
        query = (
            "[?kind=='OpenAI' && model.name=='"
            + _jmes_literal(family)
            + "' && model.lifecycleStatus=='GenerallyAvailable'].model.version"
        )
        stdout = _run_az(
            [
                self._executable,
                "cognitiveservices",
                "model",
                "list",
                "-l",
                region,
                "--query",
                query,
                "-o",
                "json",
            ],
            timeout=self._timeout,
        )
        try:
            payload = json.loads(stdout or "[]")
        except json.JSONDecodeError as exc:
            raise AzureCliResolverError(
                "az CLI returned non-JSON for PTU model version discovery"
            ) from exc
        versions = (
            sorted({value for value in payload if isinstance(value, str) and value})
            if isinstance(payload, list)
            else []
        )
        if not versions:
            raise AzureCliResolverError(
                f"no generally available model version for PTU family {family!r}"
            )
        self._versions[key] = versions[-1]
        return versions[-1]

    def _load_capacity(self, *, region: str, family: str, version: str, sku: str) -> int:
        query = urlencode(
            {
                "api-version": self._API_VERSION,
                "modelFormat": "OpenAI",
                "modelName": family,
                "modelVersion": version,
            }
        )
        url = (
            "https://management.azure.com/subscriptions/"
            + quote(self._subscription_id, safe="")
            + "/providers/Microsoft.CognitiveServices/modelCapacities?"
            + query
        )
        available = 0
        for _page in range(self._max_pages):
            payload = self._get_page(url)
            values = payload.get("value")
            if not isinstance(values, list):
                raise AzureCliResolverError("model capacities response MUST carry a value array")
            for entry in values:
                if not isinstance(entry, dict):
                    continue
                properties = entry.get("properties")
                if not isinstance(properties, dict):
                    continue
                model = properties.get("model")
                if not isinstance(model, dict):
                    continue
                if (
                    str(entry.get("location", "")).casefold() != region.casefold()
                    or properties.get("skuName") != sku
                    or model.get("format") != "OpenAI"
                    or model.get("name") != family
                    or model.get("version") != version
                ):
                    continue
                candidate = _as_int(properties.get("availableCapacity"))
                if candidate is not None:
                    available = max(available, candidate)
            next_link = payload.get("nextLink")
            if next_link is None:
                return available
            if not isinstance(next_link, str) or not _safe_management_url(next_link):
                raise AzureCliResolverError("model capacities nextLink is invalid")
            url = next_link
        raise AzureCliResolverError("model capacities pagination exceeded the page cap")

    def _get_page(self, url: str) -> dict[str, object]:
        stdout = _run_az(
            [self._executable, "rest", "--method", "get", "--url", url, "-o", "json"],
            timeout=self._timeout,
        )
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise AzureCliResolverError("az CLI returned non-JSON for model capacities") from exc
        if not isinstance(payload, dict):
            raise AzureCliResolverError("model capacities response MUST be an object")
        return payload


def _jmes_literal(value: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not value or any(character not in allowed for character in value):
        raise AzureCliResolverError("model family contains unsupported characters")
    return value


def _safe_management_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "management.azure.com"
        and parsed.username is None
        and parsed.password is None
        and parsed.fragment == ""
    )


def _as_int(value: object) -> int | None:
    """Coerce a JSON value to a non-negative int; ``None`` on any failure."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return None
    return None


_TIER_MARKERS: tuple[str, ...] = (
    ".Standard.",
    ".ProvisionedManaged.",
    ".GlobalStandard.",
    ".PayGo.",
    ".GlobalBatch.",
    ".DataZoneStandard.",
)
"""Known Azure OpenAI SKU / tier markers in the quota metric name.

The suffix *after* any of these is the family. Kept as an ordered
tuple so an entry that carries multiple markers indexes under the
suffix of the first match (matches how Azure orders these).
"""


def _family_keys(name_value: str) -> set[str]:
    """Pull every plausible family key out of an Azure quota metric name.

    A single metric name maps to multiple candidate keys so a caller
    can query by either the dotted form (``gpt-5.4-mini``) or the
    dashed form (``gpt-5-4-mini``) - see the fallback in
    :meth:`AzureCliQuotaQuery.available_capacity_tpm`.
    """
    keys: set[str] = set()
    # Suffix after any known tier marker.
    for marker in _TIER_MARKERS:
        if marker in name_value:
            keys.add(name_value.split(marker, 1)[-1])
            break
    # Always include the trailing dot segment as a fallback.
    keys.add(name_value.rsplit(".", 1)[-1])
    return keys


def _family_aliases(family: str) -> set[str]:
    aliases = {family, family.replace(".", "-")}
    if family.startswith("gpt-"):
        compact = "gpt" + family[4:]
        aliases.update((compact, compact.replace(".", "-")))
    elif family.startswith("gpt") and len(family) > 3 and family[3].isdigit():
        expanded = "gpt-" + family[3:]
        aliases.update((expanded, expanded.replace(".", "-")))
    return aliases


def _is_interactive_tpm_quota(name_value: str) -> bool:
    lowered = name_value.casefold()
    if "finetune" in lowered:
        return False
    return any(
        marker.casefold() in lowered
        for marker in (".Standard.", ".GlobalStandard.", ".DataZoneStandard.", ".PayGo.")
    )


__all__ = [
    "AzureCliCatalogQuery",
    "AzureCliPermissionQuery",
    "AzureCliProvisionedCapacityQuery",
    "AzureCliQuotaQuery",
    "AzureCliResolverError",
]
