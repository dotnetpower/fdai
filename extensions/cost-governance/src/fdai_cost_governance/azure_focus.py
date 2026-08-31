"""Read-only Azure Cost Management FOCUS adapter with injected I/O boundaries."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object],
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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes MUST be positive")
        self._transport = transport
        self._credential = credential
        self._release_id = ontology_release_id
        self._release_digest = ontology_release_digest
        self._max_bytes = max_response_bytes
        self._retention = retention
        self._clock = clock or (lambda: datetime.now(UTC))

    async def collect_cost_page(
        self,
        request: CostCollectionRequest,
        *,
        resume_token: str | None,
    ) -> CostObservationPage:
        token = await self._credential.access_token(deadline_at=request.deadline_at)
        url = self._url(request, resume_token)
        response = await self._transport.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            json_body=self._query_body(request),
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
        properties = document.get("properties", {})
        columns = properties.get("columns", [])
        rows = properties.get("rows", [])
        if not isinstance(rows, list) or len(rows) > request.page_size:
            raise ValueError("Azure Cost Management page exceeded row budget")
        if not isinstance(columns, list):
            raise ValueError("Azure Cost Management columns are invalid")
        names = [
            str(column.get("name"))
            for column in columns
            if isinstance(column, dict) and column.get("name")
        ]
        if len(names) != len(columns):
            raise ValueError("Azure Cost Management columns are invalid")
        if any(not isinstance(row, list) or len(row) != len(names) for row in rows):
            raise ValueError("Azure Cost Management rows are invalid")
        collected_at = self._clock()
        observations = tuple(
            self._observation(request, dict(zip(names, row, strict=True)), collected_at)
            for row in rows
        )
        next_link = properties.get("nextLink")
        next_token = str(next_link) if next_link else None
        if next_token is not None:
            self._require_management_url(next_token)
        return CostObservationPage(
            observations=observations,
            next_resume_token=next_token,
            complete=next_token is None,
            source_authority="azure-cost-management-query",
            bytes_read=len(response.body),
            collected_at=collected_at,
        )

    def _url(self, request: CostCollectionRequest, resume_token: str | None) -> str:
        if resume_token:
            self._require_management_url(resume_token)
            return resume_token
        scope = request.scope_id.removeprefix("/")
        query = urlencode({"api-version": "2023-11-01"})
        return (
            f"https://management.azure.com/{scope}/providers/Microsoft.CostManagement/query?{query}"
        )

    @staticmethod
    def _query_body(request: CostCollectionRequest) -> dict[str, object]:
        return {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": request.start_at.isoformat(),
                "to": request.end_at.isoformat(),
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ServiceName"}],
            },
        }

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
        required = ("ServiceName", "Cost", "UsageDate", "Currency")
        if any(not row.get(key) for key in required):
            raise ValueError("FOCUS row is missing a required source fact")
        try:
            amount = Decimal(str(row["Cost"]))
            start = datetime.strptime(str(row["UsageDate"]), "%Y%m%d").replace(
                tzinfo=collected_at.tzinfo
            )
            end = start + timedelta(days=1)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("FOCUS row has invalid amount or time") from exc
        service_id = str(row["ServiceName"]).strip()
        currency = str(row["Currency"]).strip().upper()
        source_digest = hashlib.sha256(f"{request.scope_id}\0{service_id}".encode()).hexdigest()[
            :24
        ]
        source_uri = f"cost-service:{source_digest}"
        end = min(start + timedelta(days=1), request.end_at, collected_at)
        if end <= start:
            raise ValueError("FOCUS row is outside the observed collection window")
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str).encode()
        digest = hashlib.sha256(
            request.package_id.encode() + b"\0" + request.scope_id.encode() + b"\0" + canonical
        ).hexdigest()
        return CostObservation(
            observation_id=f"costobs:{digest}",
            package_id=request.package_id,
            scope_id=request.scope_id,
            service_id=service_id,
            amount=amount,
            currency=currency,
            event_start_at=start,
            event_end_at=end,
            observed_at=end,
            recorded_at=collected_at,
            source_authority="azure-cost-management-query",
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
