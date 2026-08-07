"""Operator API-owned Change lineage read projection.

Responsibility:
Project canonical Change lineage into bounded summary and detail views.

Boundary:
Consumes immutable core lineage records and exposes no HTTP route, provider I/O,
or persistence behavior.

Authority and state:
Read-only and request-local. It cannot classify sealed operational outcomes,
approve, promote, or execute.

Dependencies:
Canonical Change lineage records and candidate-only learning projections.

Deployment:
Imported by Operator API composition after route ownership is assigned; this
package creates no process or network boundary.
"""

from .projection import (
    ChangeLineageDetailProjection,
    ChangeLineageSummaryProjection,
    project_change_lineage_detail,
    project_change_lineage_summary,
)

__all__ = [
    "ChangeLineageDetailProjection",
    "ChangeLineageSummaryProjection",
    "project_change_lineage_detail",
    "project_change_lineage_summary",
]
