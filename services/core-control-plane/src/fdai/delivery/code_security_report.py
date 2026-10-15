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
        "summary": "Review summary",
        "total": "Total findings",
        "determined": "Determined severity",
        "needs_review": "Needs evidence review",
        "potential_critical": "Critical ceiling",
        "coverage_warning": (
            "Coverage is incomplete. Missing findings must not be interpreted as a clean result."
        ),
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
        "summary": "검토 요약",
        "total": "전체 발견 사항",
        "determined": "심각도 결정됨",
        "needs_review": "근거 검토 필요",
        "potential_critical": "치명적 상한",
        "coverage_warning": (
            "검사 범위가 불완전합니다. 발견 사항이 없더라도 안전한 결과로 해석하면 안 됩니다."
        ),
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
        "severity_floor": issue.severity.floor.value,
        "severity_ceiling": issue.severity.ceiling.value,
        "severity_rationale": issue.severity.rationale,
        "deciding_facts": list(issue.severity.deciding_facts),
        "confidence": issue.confidence.value,
        "title": issue.title,
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

    coverage_complete = document["coverage_complete"] is True
    coverage = label["complete"] if coverage_complete else label["incomplete"]
    facts = [
        ("repository", document["repository_alias"]),
        ("revision", document["revision"]),
        ("revision_kind", document["revision_kind"]),
        ("source", document["source"]),
        ("generated", document["generated_at"]),
        ("decision", label["decision_" + str(document["decision"])]),
        ("coverage", coverage),
    ]
    metadata = "".join(
        f"<div><dt>{esc(label[key])}</dt><dd>{esc(value)}</dd></div>" for key, value in facts
    )
    limits = document["coverage_limits"]
    limit_html = (
        '<section class="coverage incomplete">'
        f"<div><span>{esc(label['limits'])}</span><strong>{esc(label['incomplete'])}</strong></div>"
        f"<p>{esc(label['coverage_warning'])}</p><ul>"
        + "".join(f"<li>{esc(item)}</li>" for item in limits)
        + "</ul></section>"
        if isinstance(limits, list) and limits
        else (
            '<section class="coverage complete">'
            f"<span>{esc(label['coverage'])}</span><strong>{esc(label['complete'])}</strong>"
            "</section>"
            if coverage_complete
            else (
                '<section class="coverage incomplete">'
                f"<span>{esc(label['limits'])}</span><strong>{esc(label['incomplete'])}</strong>"
                f"<p>{esc(label['coverage_warning'])}</p></section>"
            )
        )
    )
    scanners = document["scanners"]
    scanner_rows = "".join(
        f"<tr><td>{esc(run['scanner'])}</td>"
        f'<td><span class="state {"ok" if run["completed"] else "failed"}">'
        f"{esc(_cell(run['completed'], label))}</span></td>"
        f"<td>{esc(run['exit_code'])}</td></tr>"
        for run in (scanners if isinstance(scanners, list) else [])
    )
    issues = document["issues"]
    issue_rows: list[str] = []
    determined = 0
    needs_review = 0
    potential_critical = 0
    for row in issues if isinstance(issues, list) else []:
        if not isinstance(row, dict):
            continue
        severity = str(row["severity"])
        if severity == "undetermined":
            needs_review += 1
            if row["severity_ceiling"] == "critical":
                potential_critical += 1
            severity_text = f"{row['severity_floor']} - {row['severity_ceiling']}"
        else:
            determined += 1
            severity_text = severity
        title = row["title"] or str(row["weakness_class"]).replace("_", " ")
        issue_rows.append(
            "<tr>"
            f'<td><strong>{esc(title)}</strong><span class="attributes">'
            f"{esc(row['priority'])} | {esc(severity_text)} | {esc(row['confidence'])}</span>"
            f"<small>{esc(row['issue_id'])}</small></td>"
            f"<td><span>{esc(row['location'])}</span>"
            f"<small>{esc(row['identifiers'])} | {esc(row['producers'])}</small></td>"
            "</tr>"
        )
    issue_html = (
        '<div class="issue-table"><table><thead><tr>'
        f"<th>{esc(label['issues'])}</th><th>{esc(label['location'])}</th>"
        "</tr></thead><tbody>" + "".join(issue_rows) + "</tbody></table></div>"
        if issue_rows
        else f'<p class="empty">{esc(label["none"])}</p>'
    )
    metrics = (
        f"<div><span>{esc(label['total'])}</span><strong>{len(issue_rows)}</strong></div>"
        f"<div><span>{esc(label['determined'])}</span><strong>{determined}</strong></div>"
        f"<div><span>{esc(label['needs_review'])}</span><strong>{needs_review}</strong></div>"
        f"<div><span>{esc(label['potential_critical'])}</span>"
        f"<strong>{potential_critical}</strong></div>"
    )
    snapshot = (
        f'<p class="note">{esc(label["snapshot_note"])}</p>'
        if document["revision_kind"] == "snapshot"
        else ""
    )
    lang = "ko" if locale == "ko" else "en"
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'\">"
        f"<title>{esc(label['title'])}</title><style>"
        ":root{color-scheme:light;--ink:#202124;--muted:#62666b;--line:#ddd9d3;"
        "--surface:#fff;--shade:#f5f3f0;--accent:#1769aa;--warning:#8a4b08;--success:#236b3a}"
        "*{box-sizing:border-box}body{margin:0;background:#f7f6f4;color:var(--ink);"
        'font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}'
        "main{width:min(1180px,100%);margin:auto;padding:clamp(20px,4vw,48px)}"
        "header{display:grid;gap:10px;margin-bottom:28px}h1{margin:0;font-size:clamp(28px,4vw,40px);"
        "line-height:1.15;letter-spacing:-.02em}h2{margin:36px 0 12px;font-size:20px}"
        "p{margin:0}.notice{max-width:78ch;color:var(--muted)}"
        ".metadata{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;"
        "margin:0;border-block:1px solid var(--line)}.metadata div{display:grid;"
        "grid-template-columns:minmax(110px,.45fr) minmax(0,1fr);gap:12px;padding:10px 0;"
        "border-bottom:1px solid var(--line)}.metadata div:nth-last-child(-n+2){border-bottom:0}"
        "dt{color:var(--muted);font-size:12px;font-weight:650}dd{margin:0;overflow-wrap:anywhere}"
        ".coverage{display:grid;gap:8px;margin:24px 0;padding:14px 16px;"
        "border:1px solid var(--line);"
        "border-radius:8px;background:var(--surface)}.coverage>div{display:flex;"
        "justify-content:space-between;gap:12px}.coverage span{color:var(--muted);font-size:12px;"
        "font-weight:650}.coverage.incomplete{border-color:#d6a76f;background:#fff8ef}"
        ".coverage.incomplete strong{color:var(--warning)}"
        ".coverage.complete strong{color:var(--success)}"
        ".coverage ul{margin:0;padding-left:20px;color:var(--muted)}"
        ".metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));"
        "border-block:1px solid var(--line)}"
        ".metrics div{display:grid;gap:4px;padding:16px;border-left:1px solid var(--line)}"
        ".metrics div:first-child{border-left:0}.metrics span{color:var(--muted);font-size:12px;"
        "font-weight:650}.metrics strong{font-size:26px;font-variant-numeric:tabular-nums}"
        "table{width:100%;border-collapse:collapse;background:var(--surface)}"
        "th,td{padding:10px 12px;text-align:left;vertical-align:top;"
        "border-bottom:1px solid var(--line);"
        "overflow-wrap:anywhere}th{color:var(--muted);font-size:12px;font-weight:650;"
        "background:var(--shade)}td strong,td small{display:block}"
        "td small{margin-top:4px;color:var(--muted);font-size:12px}"
        ".scanner-table{max-width:560px}.state{font-weight:650}.state.ok{color:var(--success)}"
        ".state.failed{color:var(--warning)}.issue-table{overflow:hidden;"
        "border:1px solid var(--line);"
        "border-radius:8px}.issue-table th:first-child{width:46%}"
        ".issue-table th:last-child{width:54%}.attributes{display:block;margin-top:4px;"
        "color:var(--muted);font-size:12px}.note{margin:18px 0;padding:12px 14px;"
        "border-left:3px solid var(--accent);background:var(--shade)}.empty{color:var(--muted)}"
        "@media(max-width:720px){main{padding:20px 16px}.metadata{grid-template-columns:1fr}"
        ".metadata div:nth-last-child(-n+2){border-bottom:1px solid var(--line)}"
        ".metadata div:last-child{border-bottom:0}"
        ".metrics{grid-template-columns:1fr 1fr}"
        ".metrics div:nth-child(odd){border-left:0}.issue-table{border:0;overflow:visible}"
        ".issue-table table,.issue-table tbody,.issue-table tr,"
        ".issue-table td{display:block}.issue-table thead{display:none}"
        ".issue-table tr{margin-bottom:12px;border:1px solid var(--line);"
        "border-radius:8px;background:var(--surface)}"
        ".issue-table td{border-bottom:1px solid var(--line)}"
        ".issue-table td:last-child{border-bottom:0}}"
        "@media print{body{background:#fff}main{width:100%;padding:0}"
        ".coverage,.issue-table tr{break-inside:avoid}"
        ".issue-table{border-radius:0}}"
        "</style></head><body><main>"
        f"<header><h1>{esc(label['title'])}</h1>"
        f'<p class="notice">{esc(label["notice"])}</p></header>'
        f'<dl class="metadata">{metadata}</dl>{snapshot}{limit_html}'
        f'<h2>{esc(label["summary"])}</h2><section class="metrics">{metrics}</section>'
        f'<h2>{esc(label["scanners"])}</h2><table class="scanner-table"><thead><tr>'
        f"<th>{esc(label['scanner'])}</th>"
        f"<th>{esc(label['completed'])}</th><th>{esc(label['exit'])}</th></tr></thead>"
        f"<tbody>{scanner_rows}</tbody></table>"
        f"<h2>{esc(label['counts'])}</h2><ul>"
        f"<li>{esc(label['priority'])}: {esc(_counts_line(document['by_priority']))}</li>"
        f"<li>{esc(label['severity'])}: {esc(_counts_line(document['by_severity']))}</li>"
        f"<li>{esc(label['confidence'])}: {esc(_counts_line(document['by_confidence']))}</li>"
        f"</ul><h2>{esc(label['issues'])}</h2>{issue_html}</main></body></html>\n"
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
        end = min(len(lines), line_number + 3)
        selected = [(number, _bounded_line(lines[number - 1])) for number in range(start, end + 1)]
    return {
        "start_line": start,
        "highlight_start": line_number,
        "highlight_end": min(end, max(line_number, issue.fix_site.end_line or line_number)),
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
