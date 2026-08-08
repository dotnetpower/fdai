"""Rule-catalog collector - fetch + verify + snapshot pipeline.

Skeleton in this build (see ``docs/roadmap/rules-and-detection/rule-catalog-collection.md``
§ Collector Architecture). This package delivers the fetch/verify/snapshot
stages; parser plugins + normalization to rule YAML land in follow-up
phases without touching the seam boundaries here.
"""

from __future__ import annotations

from fdai.rule_catalog.pipeline.collect.collector import (
    CollectorPipeline,
    SnapshotReport,
)
from fdai.rule_catalog.pipeline.collect.fetch import (
    Fetcher,
    FetchError,
    GitCloneFetcher,
    HttpDownloadFetcher,
    LocalDirectoryFetcher,
    build_fetcher,
)

__all__ = [
    "CollectorPipeline",
    "FetchError",
    "Fetcher",
    "GitCloneFetcher",
    "HttpDownloadFetcher",
    "LocalDirectoryFetcher",
    "SnapshotReport",
    "build_fetcher",
]
