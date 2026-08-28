"""Read-only Azure Cost Management FOCUS adapter with injected I/O boundaries."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlencode, urlparse

from fdai.shared.providers.cost_governance import (
    CostCollectionRequest,
    CostObservation,
    CostObservationPage,
    CostObservationProvider,
)


@dataclass(frozen=True, slots=True)
class CostHttpResponse:
    status_code: int
    body: bytes


class CostReadCredential(Protocol):
    """Issue a read-only management-plane token."""

    async def access_token(self, *, deadline_at: datetime) -> str: ...


class CostHttpTransport(Protocol):
    """Injected HTTPS transport; implementations enforce their own timeout."""

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        deadline_at: datetime,
    ) -> CostHttpResponse: ...


class AzureFocusObservationAdapter(CostObservationProvider):
    """Translate one bounded Azure FOCUS query page into immutable facts."""

    def __init__(
        self,
        *,
        transport: CostHttpTransport,
        credential: CostReadCredential,
        ontology_release_id: str,
        ontology_release_digest: str,
        max_response_bytes: int = 2_000_000,
        retention: timedelta = timedelta(days=400),
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes MUST be positive")
        self._transport = transport
        self._credential = credential
        self._release_id = ontology_release_id
        self._release_digest = ontology_release_digest
        self._max_bytes = max_response_bytes
        self._retention = retention

    async def collect_cost_page(
        self,
        request: CostCollectionRequest,
        *,
        resume_token: str | None,
    ) -> CostObservationPage:
        token = await self._credential.access_token(deadline_at=request.deadline_at)
        url = self._url(request, resume_token)
        response = await self._transport.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            max_bytes=self._max_bytes,
            deadline_at=request.deadline_at,
        )
        if response.status_code != 200:
            raise RuntimeError(f"Azure Cost Management read failed: {response.status_code}")
        if len(response.body) > self._max_bytes:
            raise RuntimeError("Azure Cost Management response exceeded byte budget")
        try:
            document = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Azure Cost Management returned invalid JSON") from exc
        rows = document.get("properties", {}).get("rows", [])
        if not isinstance(rows, list) or len(rows) > request.page_size:
            raise ValueError("Azure Cost Management page exceeded row budget")
        collected_at = datetime.fromisoformat(str(document["collectedAt"]).replace("Z", "+00:00"))
        observations = tuple(
            self._observation(request, row, collected_at) for row in rows if isinstance(row, dict)
        )
        next_link = document.get("properties", {}).get("nextLink")
        next_token = str(next_link) if next_link else None
        if next_token is not None:
            self._require_management_url(next_token)
        return CostObservationPage(
            observations=observations,
            next_resume_token=next_token,
            complete=next_token is None,
            source_authority="azure-cost-management-focus",
            bytes_read=len(response.body),
            collected_at=collected_at,
        )

    def _url(self, request: CostCollectionRequest, resume_token: str | None) -> str:
        if resume_token:
            self._require_management_url(resume_token)
            return resume_token
        scope = request.scope_id.removeprefix("/")
        query = urlencode(
            {
                "api-version": "2023-11-01",
                "start": request.start_at.isoformat(),
                "end": request.end_at.isoformat(),
                "top": request.page_size,
                "format": "focus",
            }
        )
        return (
            f"https://management.azure.com/{scope}/providers/Microsoft.CostManagement/query?{query}"
        )

    @staticmethod
    def _require_management_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "management.azure.com":
            raise ValueError("Azure Cost Management continuation URL is not authoritative")

    def _observation(
        self,
        request: CostCollectionRequest,
        row: dict[str, object],
        collected_at: datetime,
    ) -> CostObservation:
        required = ("serviceId", "billedCost", "chargePeriodStart", "chargePeriodEnd")
        if any(not row.get(key) for key in required):
            raise ValueError("FOCUS row is missing a required source fact")
        try:
            amount = Decimal(str(row["billedCost"]))
            start = datetime.fromisoformat(str(row["chargePeriodStart"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(row["chargePeriodEnd"]).replace("Z", "+00:00"))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("FOCUS row has invalid amount or time") from exc
        source_uri = str(row.get("sourceUri") or request.scope_id)
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        return CostObservation(
            observation_id=f"costobs:{digest}",
            package_id=request.package_id,
            scope_id=request.scope_id,
            service_id=str(row["serviceId"]),
            amount=amount,
            currency=str(row.get("billingCurrency") or "USD"),
            event_start_at=start,
            event_end_at=end,
            observed_at=collected_at,
            recorded_at=collected_at,
            source_authority="azure-cost-management-focus",
            source_uri=source_uri,
            completeness=Decimal(str(row.get("completeness", "1"))),
            ontology_release_id=self._release_id,
            ontology_release_digest=self._release_digest,
            evidence_digest=f"sha256:{digest}",
            retention_until=collected_at + self._retention,
        )


__all__ = [
    "AzureFocusObservationAdapter",
    "CostHttpResponse",
    "CostHttpTransport",
    "CostReadCredential",
]
