"""Revisioned case-history facade."""

from .analysis import CaseHistoryAnalyzer, CaseHistoryReviewer
from .models import (
    CaseHistoryRevision,
    CaseKind,
    CaseSourceRecord,
    build_case_history_revision,
)
from .operational_case import (
    FailureFingerprint,
    OperationalCaseProjection,
    OperationalOutcomeClass,
)
from .service import CaseHistoryMaterializer, CaseHistoryRetentionService

__all__ = [
    "FailureFingerprint",
    "CaseHistoryRevision",
    "CaseHistoryMaterializer",
    "CaseHistoryRetentionService",
    "CaseHistoryAnalyzer",
    "CaseHistoryReviewer",
    "CaseKind",
    "CaseSourceRecord",
    "OperationalCaseProjection",
    "OperationalOutcomeClass",
    "build_case_history_revision",
]
