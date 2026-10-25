"""Unverified clone requests: metadata only, never ownership, approval or deployment evidence."""

from __future__ import annotations

import json
from datetime import UTC
from typing import TYPE_CHECKING, Any

from fdai_deployment_cli.runtime_release import is_release_id
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from fdai_release_hub.catalog_serialization import CatalogError
from fdai_release_hub.database import catalog_metadata, deployment_requests, membership, releases

if TYPE_CHECKING:
    from fdai_release_hub.store import ReleaseStore

MAX_REQUEST_BODY = 2048
MAX_STORED_REQUESTS = 100_000
SUBSCRIPTION_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class DeploymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    request_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    subscription_id: str = Field(min_length=36, max_length=36, pattern=SUBSCRIPTION_PATTERN)
    release_id: str = Field(min_length=1, max_length=64)
    channel: str = Field(
        max_length=64,
        pattern=r"^(DEV|RELEASE_CANDIDATE|RELEASE|custom-[a-z0-9]+(-[a-z0-9]+)*)$",
    )
    region: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9]*$")
    source_commit: str = Field(min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$")
    catalog_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @field_validator("release_id")
    @classmethod
    def validate_release(cls, value: str) -> str:
        if not is_release_id(value):
            raise ValueError("Use a canonical SemVer Release id.")
        return value


class RequestPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=MAX_STORED_REQUESTS)
    subscription_id: str | None = Field(
        default=None, min_length=36, max_length=36, pattern=SUBSCRIPTION_PATTERN
    )


def parse_request(raw: bytes) -> DeploymentRequest:
    """Reject duplicate keys as well as unknown fields before retaining any input."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate request fields are not supported.")
            result[key] = value
        return result

    return DeploymentRequest.model_validate(
        json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    )


def record_request(store: ReleaseStore, payload: DeploymentRequest) -> tuple[dict[str, Any], bool]:
    """Serialize eligibility and exact-id deduplication without publishing a catalog event."""
    with store.connect() as db:
        if db.dialect.name == "sqlite":
            db.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            db.execute(select(catalog_metadata).with_for_update()).all()
        existing = (
            db.execute(
                select(deployment_requests).where(
                    deployment_requests.c.request_id == payload.request_id
                )
            )
            .mappings()
            .one_or_none()
        )
        fields = payload.model_dump()
        if existing is not None:
            if any(existing[key] != value for key, value in fields.items()):
                raise CatalogError("Request id already belongs to different metadata.", 409)
            return dict(existing), False
        count = db.scalar(select(func.count()).select_from(deployment_requests))
        if count is None or count >= MAX_STORED_REQUESTS:
            raise CatalogError(
                "Deployment request capacity reached. Contact the Hub operator.", 503
            )
        release = (
            db.execute(select(releases).where(releases.c.id == payload.release_id))
            .mappings()
            .one_or_none()
        )
        if release is None or release["published_at"] is None or release["recalled_at"] is not None:
            raise CatalogError("Requested Release is unavailable or recalled.", 409)
        store._verify_release_state(
            release["manifest"],
            release["signature"],
            release["published_at"],
            release["recalled_at"],
        )
        store._verify_signature(release["manifest"], release["signature"])
        member = db.execute(
            select(membership.c.release_id).where(
                membership.c.release_id == payload.release_id,
                membership.c.channel == payload.channel,
            )
        ).first()
        if member is None:
            raise CatalogError("Requested Release does not belong to the selected channel.", 409)
        record = {
            **fields,
            "recorded_at": store.clock().astimezone(UTC).isoformat(timespec="microseconds"),
            "status": "requested",
            "trust": "self-reported",
        }
        db.execute(deployment_requests.insert().values(**record))
        return record, True


def list_requests(store: ReleaseStore, page: RequestPage) -> dict[str, Any]:
    query = select(deployment_requests)
    if page.subscription_id is not None:
        query = query.where(deployment_requests.c.subscription_id == page.subscription_id)
    query = (
        query.order_by(
            deployment_requests.c.recorded_at.desc(), deployment_requests.c.request_id.desc()
        )
        .limit(page.limit + 1)
        .offset(page.offset)
    )
    with store.connect() as db:
        rows = db.execute(query).mappings().all()
    return {
        "requests": [dict(row) for row in rows[: page.limit]],
        "limit": page.limit,
        "offset": page.offset,
        "has_more": len(rows) > page.limit,
    }
