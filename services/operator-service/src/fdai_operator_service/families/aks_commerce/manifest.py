"""Stable Operator route manifest for the AKS commerce scenario."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class AksCommerceRoute:
    """One read route owned by the AKS commerce family."""

    method: Literal["GET"]
    path: str
    name: str


AKS_COMMERCE_ROUTE_MANIFEST = (
    AksCommerceRoute("GET", "/aks-commerce/overview", "aks_commerce_overview"),
)


__all__ = ["AKS_COMMERCE_ROUTE_MANIFEST", "AksCommerceRoute"]
