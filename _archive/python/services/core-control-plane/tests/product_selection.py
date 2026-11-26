"""Select governed execution in tests only through the #1553 product profile."""

from __future__ import annotations

from fdai.runtime.product_profile import RuntimeProductSelection
from fdai_service_contracts.product_profile import ProductAddOn, ProductProfile

#: The smallest valid profile that selects the ``governed-execution`` add-on.
GOVERNED_PROFILE = ProductProfile(
    add_ons=(ProductAddOn.ENTERPRISE_IDENTITY_GOVERNANCE, ProductAddOn.GOVERNED_EXECUTION)
)


def governed_execution_selection(governed: bool) -> bool:
    """Return the composed selection for the default or the governed product profile."""

    profile = GOVERNED_PROFILE if governed else ProductProfile()
    return RuntimeProductSelection.from_profile(profile).governed_execution


__all__ = ["GOVERNED_PROFILE", "governed_execution_selection"]
