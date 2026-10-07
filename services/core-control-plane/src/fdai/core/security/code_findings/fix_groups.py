"""Fix groups: issues that one coherent change remediates together.

Grouping keys are deterministic:

- dependency issues group by package (one upgrade fixes every advisory of that package);
- hard-coded secrets group by file;
- other code issues group by weakness class and file, so one guidance block applies.

Each group carries the paths a coding agent may edit (fix sites, code-flow files, and test paths;
for upgrades the manifest directory), its maximum remediation depth, and the project root and test
commands supplied by acquisition or the operator. Groups are ordered so upgrades and configuration
come before code changes.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace

from fdai.core.security.code_findings.canonical import (
    DEPENDENCY_CLASS,
    SECRET_CLASS,
)
from fdai.core.security.code_findings.models import (
    CodeSecurityIssue,
    FixGroup,
    ProjectRoot,
    TestFeasibility,
)
from fdai.rule_catalog.code_security import (
    AutofixEligibility,
    CodeSecurityCatalog,
    FixClass,
    Priority,
    RemediationDepth,
)

_FIX_ORDER = {
    FixClass.DEPENDENCY_BUMP: 0,
    FixClass.CONFIG_CHANGE: 1,
    FixClass.LOCAL_CODE_FIX: 2,
    FixClass.SECRET_REMOVAL: 3,
    FixClass.DESIGN_CHANGE: 4,
}
_UNCLASSIFIED_GUIDANCE = (
    "Follow the producer rule's documented fix and confirm the root cause in code before "
    "changing it."
)


def _group_key(issue: CodeSecurityIssue) -> tuple[str, str]:
    if issue.weakness_class == DEPENDENCY_CLASS:
        return (DEPENDENCY_CLASS, issue.package or issue.fix_site.path)
    if issue.weakness_class == SECRET_CLASS:
        return (SECRET_CLASS, issue.fix_site.path)
    return (issue.weakness_class, issue.fix_site.path)


def _project_for(path: str, roots: Sequence[ProjectRoot]) -> ProjectRoot | None:
    matches = [
        root
        for root in roots
        if root.path in ("", ".")
        or path == root.path
        or path.startswith(root.path.rstrip("/") + "/")
    ]
    return max(matches, key=lambda root: len(root.path)) if matches else None


def _allowed_paths(
    issues: Sequence[CodeSecurityIssue], test_globs: Sequence[str], include_flow_paths: bool
) -> tuple[str, ...]:
    paths: set[str] = set()
    for issue in issues:
        if issue.weakness_class == DEPENDENCY_CLASS:
            for layer in issue.layers or (issue.fix_site.path,):
                directory = posixpath.dirname(layer)
                paths.add(f"{directory}/*" if directory else "*")
            continue
        paths.add(issue.fix_site.path)
        if include_flow_paths:
            paths.update(step.path for step in issue.code_flow)
    return tuple(sorted(paths)) + tuple(test_globs)


def build_fix_groups(
    issues: Sequence[CodeSecurityIssue],
    catalog: CodeSecurityCatalog,
    project_roots: Sequence[ProjectRoot] = (),
    *,
    include_flow_paths: bool = True,
) -> tuple[FixGroup, ...]:
    """Group canonical issues into ordered fix groups with stable ``FG-NNN`` ids.

    ``include_flow_paths=False`` keeps code-flow files out of ``allowed_paths`` for minimized
    packs, which must not disclose code flows.
    """
    grouped: dict[tuple[str, str], list[CodeSecurityIssue]] = defaultdict(list)
    for issue in issues:
        grouped[_group_key(issue)].append(issue)
    drafts: list[tuple[tuple[int, int, str, str], FixGroup]] = []
    test_globs = catalog.remediation_policy.test_path_globs
    for (class_id, subject), members in grouped.items():
        entry = catalog.weakness_classes.classes.get(class_id)
        fix_class = entry.fix_class if entry else FixClass.LOCAL_CODE_FIX
        eligibility = entry.autofix_eligibility if entry else AutofixEligibility.ASSISTED
        max_depth = entry.max_depth if entry else RemediationDepth.D2
        priority = min((issue.priority.priority for issue in members), key=lambda p: p.value)
        root = _project_for(members[0].fix_site.path, project_roots)
        targeted = root.targeted_test_command if root else None
        full = root.full_test_command if root else None
        if class_id == DEPENDENCY_CLASS:
            title = f"Upgrade {subject}"
        elif class_id == SECRET_CLASS:
            title = f"Remove hard-coded secret from {subject}"
        else:
            title = f"{entry.title if entry else members[0].title.split(' in ')[0]} in {subject}"
        group = FixGroup(
            group_id="",
            title=title,
            weakness_class=class_id,
            fix_class=fix_class,
            autofix_eligibility=eligibility,
            max_depth=max_depth,
            priority=Priority(priority),
            issue_ids=tuple(issue.issue_id for issue in members),
            allowed_paths=_allowed_paths(members, test_globs, include_flow_paths),
            guidance=entry.guidance if entry else _UNCLASSIFIED_GUIDANCE,
            project_root=root.path if root else "",
            ecosystem=root.ecosystem if root else "unknown",
            targeted_test_command=targeted,
            full_test_command=full,
            test_feasibility=TestFeasibility.AVAILABLE
            if (targeted or full)
            else TestFeasibility.UNKNOWN,
            order=0,
        )
        drafts.append(((_FIX_ORDER[fix_class], int(priority.value[1]), class_id, subject), group))
    drafts.sort(key=lambda item: item[0])
    return tuple(
        replace(group, group_id=f"FG-{index:03d}", order=index)
        for index, (_, group) in enumerate(drafts, start=1)
    )


__all__ = ["build_fix_groups"]
