"""Code-security findings: canonical issues, unambiguous severity, and remediation packs.

See ``docs/roadmap/operations/code-security-findings.md`` for the design.
"""

from fdai.core.security.code_findings.canonical import AnalysisContext, build_issues
from fdai.core.security.code_findings.diff_guard import evaluate_diff
from fdai.core.security.code_findings.fix_groups import build_fix_groups
from fdai.core.security.code_findings.models import (
    CodeSecurityIssue,
    FixGroup,
    InstanceFacts,
    Lane,
    Occurrence,
    ProjectRoot,
    SeverityAssessment,
)
from fdai.core.security.code_findings.pack import (
    PackMode,
    PackRequest,
    RemediationPack,
    render_remediation_pack,
)
from fdai.core.security.code_findings.result_import import (
    ClaimStatus,
    ImportedRemediationResult,
    PackRecord,
    RemediationResultRejectedError,
    import_remediation_result,
)
from fdai.core.security.code_findings.sarif import (
    SarifIngestContext,
    SarifIngestError,
    SarifIngestResult,
    ingest_sarif,
)

__all__ = [
    "AnalysisContext",
    "ClaimStatus",
    "CodeSecurityIssue",
    "FixGroup",
    "ImportedRemediationResult",
    "InstanceFacts",
    "Lane",
    "Occurrence",
    "PackMode",
    "PackRecord",
    "PackRequest",
    "ProjectRoot",
    "RemediationPack",
    "RemediationResultRejectedError",
    "SarifIngestContext",
    "SarifIngestError",
    "SarifIngestResult",
    "SeverityAssessment",
    "build_fix_groups",
    "build_issues",
    "evaluate_diff",
    "import_remediation_result",
    "ingest_sarif",
    "render_remediation_pack",
]
