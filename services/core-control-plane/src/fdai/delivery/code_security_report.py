"""Human-readable scan reports for one code-security scan job.

The report lists the review decision, scanner coverage, counts, and one row per canonical issue
with its priority, severity, confidence, weakness class, CWE, fix-site location, and producers. It
never includes source code, scanner messages, code flows, or secret values, so it can be shared
the same way as the SARIF files it summarizes. Markdown, HTML, and JSON are written side by side;
the HTML escapes every value and loads nothing external.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from fdai.core.security.code_findings.models import CodeSecurityIssue
from fdai.core.security.code_findings.review_signal import review_decision
from fdai.delivery.code_security_scan_job import ScanJobResult

_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "title": "FDAI code-security scan report",
        "repository": "Repository",
        "revision": "Revision",
        "revision_kind": "Revision kind",
        "source": "Source",
        "generated": "Generated",
        "decision": "Decision",
        "coverage": "Coverage",
        "complete": "complete",
        "incomplete": "incomplete",
        "limits": "Coverage limits",
        "scanners": "Scanners",
        "scanner": "Scanner",
        "completed": "Completed",
        "exit": "Exit code",
        "counts": "Counts",
        "issues": "Issues",
        "id": "Issue",
        "priority": "Priority",
        "severity": "Severity",
        "confidence": "Confidence",
        "class": "Weakness class",
        "cwe": "CWE or advisory",
        "location": "Location",
        "yes": "yes",
        "no": "no",
        "decision_urgent": "urgent",
        "decision_open": "open",
        "decision_clear": "clear",
        "decision_coverage_incomplete": "coverage incomplete",
        "producers": "Producers",
        "kev": "Known exploited",
        "none": "No issue was found.",
        "notice": (
            "This report contains no source code, scanner messages, or secret values. "
            "Findings are claims until a rescan verifies a fix; the report grants no authority."
        ),
        "next": "Next step",
        "next_body": "Build a remediation pack from the scan SARIF with:",
        "snapshot_note": (
            "This scan used an uncommitted snapshot. Remediation packs and fix verification "
            "need a committed revision."
        ),
    },
    "ko": {
        "title": "FDAI 코드 보안 스캔 보고서",
        "repository": "저장소",
        "revision": "리비전",
        "revision_kind": "리비전 종류",
        "source": "출처",
        "generated": "생성 시각",
        "decision": "판정",
        "coverage": "검사 범위",
        "complete": "완전",
        "incomplete": "불완전",
        "limits": "검사 범위 한계",
        "scanners": "스캐너",
        "scanner": "스캐너",
        "completed": "완료",
        "exit": "종료 코드",
        "counts": "건수",
        "issues": "이슈",
        "id": "이슈",
        "priority": "우선순위",
        "severity": "심각도",
        "confidence": "신뢰도",
        "class": "취약점 유형",
        "cwe": "CWE 또는 권고",
        "location": "위치",
        "yes": "예",
        "no": "아니요",
        "decision_urgent": "긴급",
        "decision_open": "열림",
        "decision_clear": "이상 없음",
        "decision_coverage_incomplete": "검사 범위 불완전",
        "producers": "탐지 도구",
        "kev": "실제 악용 확인",
        "none": "발견된 이슈가 없습니다.",
        "notice": (
            "이 보고서에는 소스 코드, 스캐너 메시지, 비밀 값이 들어 있지 않습니다. "
            "발견 사항은 다시 스캔해 수정이 확인되기 전까지 주장일 뿐이며, 이 보고서는 어떤 권한도 "
            "부여하지 않습니다."
        ),
        "next": "다음 단계",
        "next_body": "스캔한 SARIF로 수정 지침 묶음을 만들려면 다음을 실행합니다.",
        "snapshot_note": (
            "이 스캔은 커밋하지 않은 스냅샷을 대상으로 했습니다. 수정 지침 묶음과 수정 확인에는 "
            "커밋된 리비전이 필요합니다."
        ),
    },
}


@dataclass(frozen=True, slots=True)
class ScanReportPaths:
    markdown: Path
    html: Path
    json: Path


def _location(issue: CodeSecurityIssue) -> str:
    line = issue.fix_site.start_line
    where = f"{issue.fix_site.path}:{line}" if line else issue.fix_site.path
    return f"{where} ({issue.package})" if issue.package else where


def _identifiers(issue: CodeSecurityIssue) -> list[str]:
    """CWE ids for code issues, or up to three advisory ids for dependency issues."""
    if issue.cwe_ids:
        return [f"CWE-{cwe}" for cwe in issue.cwe_ids]
    return sorted(issue.advisory_ids)[:3]


def _issue_row(issue: CodeSecurityIssue) -> dict[str, object]:
    return {
        "issue_id": issue.issue_id,
        "priority": issue.priority.priority.value,
        "due_days": issue.priority.due_days,
        "severity": issue.severity.label,
        "confidence": issue.confidence.value,
        "weakness_class": issue.weakness_class,
        "cwe": [f"CWE-{cwe}" for cwe in issue.cwe_ids],
        "identifiers": _identifiers(issue),
        "location": _location(issue),
        "producers": list(issue.producers),
        "known_exploited": issue.known_exploited,
        "package": issue.package,
        "advisories": list(issue.advisory_ids),
    }


def scan_report_document(
    result: ScanJobResult, *, repository_alias: str, source_label: str, generated_at: str
) -> dict[str, object]:
    """Return the machine-readable report that the Markdown and HTML views render."""
    package = result.package
    return {
        "kind": "code-security-scan-report",
        "schema_version": "1.0.0",
        "repository_alias": repository_alias,
        "revision": result.revision,
        "revision_kind": result.revision_kind,
        "source": source_label,
        "generated_at": generated_at,
        "decision": review_decision(package),
        "coverage_complete": package["coverage_complete"],
        "coverage_limits": list(result.coverage_limits),
        "scanners": [
            {"scanner": run.scanner_id, "completed": run.completed, "exit_code": run.exit_code}
            for run in result.runs
        ],
        "by_priority": package["by_priority"],
        "by_severity": package["by_severity"],
        "by_confidence": package["by_confidence"],
        "issues": [_issue_row(issue) for issue in result.issues],
        "export_sarif_args": [f"{path}:deterministic" for path in result.sarif_files],
        "grants_authority": False,
    }


def _cell(value: object, label: dict[str, str]) -> object:
    """Localize booleans; every other value is rendered as-is."""
    if isinstance(value, bool):
        return label["yes"] if value else label["no"]
    return value


def _md(value: object) -> str:
    text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("`", "'").replace("\n", " ")


def _counts_line(counts: object) -> str:
    if not isinstance(counts, dict):
        return ""
    return ", ".join(f"{key} {value}" for key, value in counts.items())


def render_markdown(document: dict[str, object], locale: str = "en") -> str:
    """Render the report as Markdown with every cell escaped."""
    label = _LABELS.get(locale, _LABELS["en"])
    coverage = label["complete"] if document["coverage_complete"] else label["incomplete"]
    lines = [
        f"# {label['title']}",
        "",
        f"> {label['notice']}",
        "",
        f"- **{label['repository']}:** {_md(document['repository_alias'])}",
        f"- **{label['revision']}:** `{_md(document['revision'])}`",
        f"- **{label['revision_kind']}:** {_md(document['revision_kind'])}",
        f"- **{label['source']}:** {_md(document['source'])}",
        f"- **{label['generated']}:** {_md(document['generated_at'])}",
        f"- **{label['decision']}:** {label['decision_' + str(document['decision'])]}",
        f"- **{label['coverage']}:** {coverage}",
        "",
    ]
    if document["revision_kind"] == "snapshot":
        lines += [f"> {label['snapshot_note']}", ""]
    limits = document["coverage_limits"]
    if isinstance(limits, list) and limits:
        lines += [f"## {label['limits']}", "", *[f"- {_md(item)}" for item in limits], ""]
    lines += [
        f"## {label['scanners']}",
        "",
        f"| {label['scanner']} | {label['completed']} | {label['exit']} |",
        "|---|---|---|",
    ]
    scanners = document["scanners"]
    for run in scanners if isinstance(scanners, list) else []:
        lines.append(
            f"| {_md(run['scanner'])} | {_md(_cell(run['completed'], label))} "
            f"| {_md(run['exit_code'])} |"
        )
    lines += [
        "",
        f"## {label['counts']}",
        "",
        f"- **{label['priority']}:** {_counts_line(document['by_priority'])}",
        f"- **{label['severity']}:** {_counts_line(document['by_severity'])}",
        f"- **{label['confidence']}:** {_counts_line(document['by_confidence'])}",
        "",
        f"## {label['issues']}",
        "",
    ]
    issues = document["issues"]
    if isinstance(issues, list) and issues:
        lines += [
            f"| {label['id']} | {label['priority']} | {label['severity']} | {label['confidence']} "
            f"| {label['class']} | {label['cwe']} | {label['location']} | {label['producers']} "
            f"| {label['kev']} |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row in issues:
            lines.append(
                "| "
                + " | ".join(
                    _md(_cell(row[key], label))
                    for key in (
                        "issue_id",
                        "priority",
                        "severity",
                        "confidence",
                        "weakness_class",
                        "identifiers",
                        "location",
                        "producers",
                        "known_exploited",
                    )
                )
                + " |"
            )
    else:
        lines.append(label["none"])
    exports = document["export_sarif_args"]
    if document["revision_kind"] == "commit" and isinstance(exports, list) and exports:
        sarif = " ".join(f"--sarif {_md(item)}" for item in exports)
        lines += [
            "",
            f"## {label['next']}",
            "",
            label["next_body"],
            "",
            "```bash",
            f"fdai-code-security export --revision {document['revision']} "
            f"--repo-alias {_md(document['repository_alias'])} {sarif} "
            "--out PACK_DIR --registry REGISTRY --provider PROVIDER",
            "```",
        ]
    return "\n".join(lines) + "\n"


def render_html(document: dict[str, object], locale: str = "en") -> str:
    """Render a self-contained HTML report; every value is escaped and nothing is loaded."""
    label = _LABELS.get(locale, _LABELS["en"])

    def esc(value: object) -> str:
        text = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
        return html.escape(text, quote=True)

    coverage = label["complete"] if document["coverage_complete"] else label["incomplete"]
    facts = [
        ("repository", document["repository_alias"]),
        ("revision", document["revision"]),
        ("revision_kind", document["revision_kind"]),
        ("source", document["source"]),
        ("generated", document["generated_at"]),
        ("decision", label["decision_" + str(document["decision"])]),
        ("coverage", coverage),
    ]
    rows = "".join(
        f"<tr><th>{esc(label[key])}</th><td>{esc(value)}</td></tr>" for key, value in facts
    )
    limits = document["coverage_limits"]
    limit_html = (
        f"<h2>{esc(label['limits'])}</h2><ul>"
        + "".join(f"<li>{esc(item)}</li>" for item in limits)
        + "</ul>"
        if isinstance(limits, list) and limits
        else ""
    )
    scanners = document["scanners"]
    scanner_rows = "".join(
        f"<tr><td>{esc(run['scanner'])}</td><td>{esc(_cell(run['completed'], label))}</td>"
        f"<td>{esc(run['exit_code'])}</td></tr>"
        for run in (scanners if isinstance(scanners, list) else [])
    )
    keys = (
        "issue_id",
        "priority",
        "severity",
        "confidence",
        "weakness_class",
        "identifiers",
        "location",
        "producers",
        "known_exploited",
    )
    heads = (
        "id",
        "priority",
        "severity",
        "confidence",
        "class",
        "cwe",
        "location",
        "producers",
        "kev",
    )
    issues = document["issues"]
    issue_html = (
        "<table><thead><tr>"
        + "".join(f"<th>{esc(label[key])}</th>" for key in heads)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join(f"<td>{esc(_cell(row[key], label))}</td>" for key in keys) + "</tr>"
            for row in issues
        )
        + "</tbody></table>"
        if isinstance(issues, list) and issues
        else f"<p>{esc(label['none'])}</p>"
    )
    snapshot = (
        f'<p class="note">{esc(label["snapshot_note"])}</p>'
        if document["revision_kind"] == "snapshot"
        else ""
    )
    lang = "ko" if locale == "ko" else "en"
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'\">"
        f"<title>{esc(label['title'])}</title><style>"
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#1b1b1b}"
        "table{border-collapse:collapse;margin:1rem 0}th,td{border:1px solid #ccc;"
        "padding:.3rem .6rem;text-align:left;vertical-align:top}.note{background:#f4f4f4;"
        "padding:.6rem}</style></head><body>"
        f'<h1>{esc(label["title"])}</h1><p class="note">{esc(label["notice"])}</p>'
        f"<table>{rows}</table>{snapshot}{limit_html}"
        f"<h2>{esc(label['scanners'])}</h2><table><thead><tr><th>{esc(label['scanner'])}</th>"
        f"<th>{esc(label['completed'])}</th><th>{esc(label['exit'])}</th></tr></thead>"
        f"<tbody>{scanner_rows}</tbody></table>"
        f"<h2>{esc(label['counts'])}</h2><ul>"
        f"<li>{esc(label['priority'])}: {esc(_counts_line(document['by_priority']))}</li>"
        f"<li>{esc(label['severity'])}: {esc(_counts_line(document['by_severity']))}</li>"
        f"<li>{esc(label['confidence'])}: {esc(_counts_line(document['by_confidence']))}</li>"
        f"</ul><h2>{esc(label['issues'])}</h2>{issue_html}</body></html>\n"
    )


def render_sarif(
    result: ScanJobResult,
    *,
    repository_alias: str,
    generated_at: str,
) -> str:
    """Render bounded canonical issues as inert SARIF 2.1.0 without scanner messages or code."""
    severity_level = {
        "critical": "error",
        "high": "error",
        "medium": "warning",
        "low": "note",
        "undetermined": "warning",
    }
    results = []
    for issue in result.issues:
        region = (
            {"startLine": issue.fix_site.start_line}
            if issue.fix_site.start_line is not None
            else {}
        )
        results.append(
            {
                "ruleId": issue.weakness_class,
                "level": severity_level.get(issue.severity.label, "warning"),
                "message": {"text": f"{issue.issue_id}: canonical FDAI code-security issue"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": issue.fix_site.path},
                            **({"region": region} if region else {}),
                        }
                    }
                ],
                "properties": {
                    "issue_id": issue.issue_id,
                    "title": issue.title,
                    "priority": issue.priority.priority.value,
                    "severity": issue.severity.label,
                    "severity_floor": issue.severity.floor.value,
                    "severity_ceiling": issue.severity.ceiling.value,
                    "severity_rationale": issue.severity.rationale,
                    "deciding_facts": list(issue.severity.deciding_facts),
                    "confidence": issue.confidence.value,
                    "cwe_ids": [f"CWE-{cwe}" for cwe in issue.cwe_ids],
                    "advisory_ids": sorted(issue.advisory_ids)[:3],
                    "package": issue.package,
                    "producers": list(issue.producers),
                    "known_exploited": issue.known_exploited,
                    "code_context": _code_context(result, issue),
                    "flow_steps": _flow_steps(issue),
                },
            }
        )
    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "FDAI",
                        "informationUri": "https://github.com/dotnetpower/fdai",
                        "rules": [],
                    }
                },
                "automationDetails": {
                    "id": f"{repository_alias}/{result.revision}",
                },
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "endTimeUtc": generated_at,
                        "properties": {
                            "coverage_complete": result.package["coverage_complete"],
                            "coverage_limits": list(result.coverage_limits),
                        },
                    }
                ],
                "results": results,
            }
        ],
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"


def _bounded_line(value: str) -> str:
    cleaned = "".join(
        character if character >= " " or character == "\t" else " " for character in value
    )
    return cleaned[:240]


def _redacted_secret_line(value: str) -> str:
    line = _bounded_line(value)
    match = re.match(r"^(\s*[^:=]{1,120}\s*[:=])", line)
    return (
        f'{match.group(1)} "<sensitive value redacted>"'
        if match
        else "<sensitive content redacted>"
    )


def _code_context(result: ScanJobResult, issue: CodeSecurityIssue) -> dict[str, object] | None:
    root = result.source_path
    line_number = issue.fix_site.start_line
    if root is None or line_number is None or line_number <= 0:
        return None
    target = (root / issue.fix_site.path).resolve()
    if (
        not target.is_relative_to(root.resolve())
        or not target.is_file()
        or target.stat().st_size > 1_000_000
    ):
        return None
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if line_number > len(lines):
        return None
    secret = any(producer.casefold() == "gitleaks" for producer in issue.producers)
    if secret:
        selected = [(line_number, _redacted_secret_line(lines[line_number - 1]))]
        start = line_number
        end = line_number
    else:
        start = max(1, line_number - 3)
        end = min(len(lines), max(line_number, issue.fix_site.end_line or line_number) + 3)
        selected = [(number, _bounded_line(lines[number - 1])) for number in range(start, end + 1)]
    return {
        "start_line": start,
        "highlight_start": line_number,
        "highlight_end": issue.fix_site.end_line or line_number,
        "redacted": secret,
        "lines": [{"number": number, "text": text} for number, text in selected],
    }


def _flow_steps(issue: CodeSecurityIssue) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for instance in issue.instances:
        if instance.source is None:
            continue
        key = (instance.source.path, instance.source.line, "source")
        if key not in seen:
            seen.add(key)
            steps.append({"kind": "source", "path": key[0], "line": key[1]})
    sink = (issue.fix_site.path, issue.fix_site.start_line, "sink")
    if sink not in seen:
        steps.append({"kind": "sink", "path": sink[0], "line": sink[1]})
    return steps[:12]


def write_scan_report(
    result: ScanJobResult,
    out_dir: Path,
    *,
    repository_alias: str,
    source_label: str,
    generated_at: str,
    locale: str = "en",
) -> ScanReportPaths:
    """Write ``report.md``, ``report.html``, and ``report.json`` with owner-only permissions."""
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    document = scan_report_document(
        result,
        repository_alias=repository_alias,
        source_label=source_label,
        generated_at=generated_at,
    )
    paths = ScanReportPaths(
        markdown=out_dir / "report.md",
        html=out_dir / "report.html",
        json=out_dir / "report.json",
    )
    for path, text in (
        (paths.markdown, render_markdown(document, locale)),
        (paths.html, render_html(document, locale)),
        (paths.json, json.dumps(document, indent=2, ensure_ascii=False) + "\n"),
    ):
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
    return paths


__all__ = [
    "ScanReportPaths",
    "render_html",
    "render_markdown",
    "render_sarif",
    "scan_report_document",
    "write_scan_report",
]
