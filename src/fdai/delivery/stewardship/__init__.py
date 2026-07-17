"""Delivery-layer stewardship adapters (Microsoft Graph identity seams)."""

from __future__ import annotations

from fdai.delivery.stewardship.graph_directory import (
    GraphGroupMembershipProvider,
    GraphIdentityDirectory,
    GraphPersonDirectory,
    TokenProvider,
)

__all__ = [
    "GraphGroupMembershipProvider",
    "GraphIdentityDirectory",
    "GraphPersonDirectory",
    "TokenProvider",
]
