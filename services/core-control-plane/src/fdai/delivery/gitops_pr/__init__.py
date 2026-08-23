"""GitOps PR-native remediation adapter (GitHub App / Azure DevOps).

Public exports (P1 W-3 Step 3e):

- :class:`~fdai.delivery.gitops_pr.adapter.GitOpsPrAdapter` -
  GitHub REST implementation of the
  :class:`~fdai.shared.providers.remediation_pr.RemediationPrPublisher`
  Protocol. Bound at the composition root; ``core/`` never imports it.
- :class:`~fdai.delivery.gitops_pr.adapter.GitOpsPrConfig` /
  :class:`~fdai.delivery.gitops_pr.adapter.GitOpsPrError` -
  adapter-level data types.
"""

from fdai.delivery.gitops_pr.adapter import (
    GitOpsPrAdapter,
    GitOpsPrConfig,
    GitOpsPrError,
)
from fdai.delivery.gitops_pr.catalog_review import GitOpsCatalogReviewPublisher
from fdai.delivery.gitops_pr.catalog_validator import DeterministicCatalogValidator

__all__ = [
    "DeterministicCatalogValidator",
    "GitOpsCatalogReviewPublisher",
    "GitOpsPrAdapter",
    "GitOpsPrConfig",
    "GitOpsPrError",
]
