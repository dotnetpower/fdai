#!/usr/bin/env python3
"""Move roadmap implementation status into mirrored delivery ledgers."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
from collections.abc import Iterable
from datetime import date
from pathlib import Path, PurePosixPath
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP_ROOT = PurePosixPath("docs/roadmap")
LEDGER_ROOT = PurePosixPath("docs/roadmap-implementation")
ENGLISH_STATUS = "## Implementation status"
KOREAN_STATUS = "## 구현 상태"
ENGLISH_RELATED = "## Related docs"
KOREAN_RELATED = "## 관련 문서"
ENGLISH_RELATED_ALIASES = (
    "## Related documents",
    "## Related Documents",
    "## Related Docs",
    "## Related",
)
KOREAN_RELATED_ALIASES = ("## Related docs",)
KOREAN_STATUS_ALIASES = ("## 구현 현황",)
LINK_PATTERN = re.compile(r"(\[[^\]]*\]\()([^)\s]+)([^)]*\))")
FRONT_MATTER_SHA = re.compile(r"(?m)^translation_source_sha:.*$")
FRONT_MATTER_REVISED = re.compile(r"(?m)^translation_revised:.*$")
HISTORY_ROW = re.compile(r"^\|\s*\d{4}-\d{2}-\d{2}\s*\|")


class OwnerMigration(NamedTuple):
    owner: str
    ledger: str
    removed_english_lines: int
    removed_korean_lines: int


class MigrationPlan(NamedTuple):
    migrations: tuple[OwnerMigration, ...]
    writes: dict[Path, str]


def _heading_ranges(lines: list[str], heading: str) -> list[tuple[int, int]]:
    indexes: list[int] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.strip() == heading:
            indexes.append(index)
    ranges: list[tuple[int, int]] = []
    for start in indexes:
        end = len(lines)
        in_fence = False
        for index in range(start + 1, len(lines)):
            line = lines[index]
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            elif not in_fence and line.startswith("## "):
                end = index
                break
        ranges.append((start, end))
    return ranges


def _remove_status_section(
    lines: list[str], heading: str, *, required: bool, relative: str
) -> tuple[list[str], list[str]]:
    ranges = _heading_ranges(lines, heading)
    if len(ranges) > 1:
        raise ValueError(f"{relative}: expected exactly one '{heading}' section")
    if not ranges:
        if required:
            raise ValueError(f"{relative}: expected exactly one '{heading}' section")
        return lines, []
    start, end = ranges[0]
    section = lines[start:end]
    remaining = lines[:start] + lines[end:]
    while start < len(remaining) and start > 0 and not remaining[start - 1].strip():
        del remaining[start - 1]
        start -= 1
    return remaining, section


def _remove_status_callouts(lines: list[str], prefix: str) -> tuple[list[str], list[list[str]]]:
    remaining: list[str] = []
    blocks: list[list[str]] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith(prefix):
            remaining.append(lines[index])
            index += 1
            continue
        block: list[str] = []
        while index < len(lines) and lines[index].startswith(">"):
            block.append(lines[index])
            index += 1
        blocks.append(block)
        if index < len(lines) and not lines[index].strip():
            index += 1
    return remaining, blocks


def _ledger_relative(owner_relative: str) -> str:
    owner = PurePosixPath(owner_relative)
    return str(LEDGER_ROOT / owner.relative_to(ROADMAP_ROOT))


def _relative_link(from_relative: str, to_relative: str) -> str:
    return os.path.relpath(
        to_relative,
        start=str(PurePosixPath(from_relative).parent),
    )


def _is_exempt_owner(relative: str) -> bool:
    path = PurePosixPath(relative)
    name = path.name.lower()
    return (
        name in {"readme.md", "index.md", "code-map.md", "code-map-implementation-ledger.md"}
        or relative == "docs/roadmap/architecture/fdai-constitution.md"
        or "decisions" in path.parts
    )


def _rebase_links(
    text: str,
    *,
    source_relative: str,
    destination_relative: str,
    repo_root: Path,
) -> str:
    source_dir = (repo_root / source_relative).parent
    destination_dir = (repo_root / destination_relative).parent
    owner_target = os.path.relpath(repo_root / source_relative, start=destination_dir)

    def replace(match: re.Match[str]) -> str:
        target = match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "//")):
            return match.group(0)
        if target.startswith("#"):
            rebased = f"{PurePosixPath(owner_target)}{target}"
            return f"{match.group(1)}{rebased}{match.group(3)}"
        path_part, marker, fragment = target.partition("#")
        query_part = ""
        if "?" in path_part:
            path_part, query = path_part.split("?", 1)
            query_part = f"?{query}"
        if not path_part or ":" in path_part.split("/", 1)[0]:
            return match.group(0)
        resolved = (source_dir / path_part).resolve()
        if fragment == "implementation-status":
            roadmap_root = (repo_root / ROADMAP_ROOT).resolve()
            try:
                roadmap_relative = resolved.relative_to(roadmap_root)
            except ValueError:
                roadmap_relative = None
            if roadmap_relative is not None:
                mirrored = (repo_root / LEDGER_ROOT / roadmap_relative).resolve()
                target_is_inline = resolved.is_file() and ENGLISH_STATUS in resolved.read_text(
                    encoding="utf-8"
                )
                if mirrored.is_file() or target_is_inline:
                    resolved = mirrored
        rebased_path = PurePosixPath(os.path.relpath(resolved, start=destination_dir))
        suffix = query_part + (f"#{fragment}" if marker else "")
        return f"{match.group(1)}{rebased_path}{suffix}{match.group(3)}"

    return LINK_PATTERN.sub(replace, text)


def _add_related_link(
    lines: list[str],
    *,
    heading: str,
    label: str,
    link_label: str,
    link: str,
    relative: str,
    aliases: tuple[str, ...] = (),
    normalize_alias: bool = False,
) -> list[str]:
    if any(f"]({link})" in line for line in lines):
        return lines
    matched = [
        (candidate, start, end)
        for candidate in (heading, *aliases)
        for start, end in _heading_ranges(lines, candidate)
    ]
    if len(matched) > 1:
        raise ValueError(f"{relative}: expected at most one '{heading}' section")
    row = f"| {label} | [{link_label}]({link}) |"
    if not matched:
        header = (
            "| To learn about | Read |"
            if heading == ENGLISH_RELATED
            else "| 알아볼 내용 | 읽을 문서 |"
        )
        separator = (
            "|----------------|------|"
            if heading == ENGLISH_RELATED
            else "|-------------|-----------|"
        )
        return lines + [
            "",
            heading,
            "",
            header,
            separator,
            row,
        ]
    matched_heading, start, end = matched[0]
    if normalize_alias and matched_heading != heading:
        lines = lines.copy()
        lines[start] = heading
    for index in range(start + 1, end - 1):
        if lines[index].lstrip().startswith("|") and re.fullmatch(
            r"\s*\|(?:\s*:?-{3,}:?\s*\|){2}\s*", lines[index + 1]
        ):
            return lines[: index + 2] + [row] + lines[index + 2 :]
    insertion = start + 1
    while insertion < end and not lines[insertion].strip():
        insertion += 1
    bullet = f"- [{link_label}]({link}) - {label}"
    return lines[:insertion] + [bullet] + lines[insertion:]


def _git_blob_sha(text: str) -> str:
    payload = text.encode("utf-8")
    header = f"blob {len(payload)}\0".encode()
    return hashlib.sha1(header + payload).hexdigest()  # noqa: S324 - Git object identity


def _refresh_korean_metadata(content: str, english: str, *, relative: str) -> str:
    sha = _git_blob_sha(english)
    if not FRONT_MATTER_SHA.search(content):
        raise ValueError(f"{relative}: missing translation_source_sha")
    content = FRONT_MATTER_SHA.sub(f"translation_source_sha: {sha}", content, count=1)
    if FRONT_MATTER_REVISED.search(content):
        content = FRONT_MATTER_REVISED.sub(
            f"translation_revised: {date.today().isoformat()}", content, count=1
        )
    return content


def _render_ledger(
    *,
    owner_relative: str,
    ledger_relative: str,
    owner_lines: list[str],
    status_lines: list[str],
    callouts: list[list[str]],
    repo_root: Path,
) -> str:
    title = next((line[2:].strip() for line in owner_lines if line.startswith("# ")), None)
    if not title:
        raise ValueError(f"{owner_relative}: missing H1 title")
    status_lines = _normalize_status_lines(status_lines, owner_relative=owner_relative)
    rendered = [
        f"# {title} implementation ledger",
        "",
        "This delivery ledger preserves reviewable implementation scope, append-only transitions,",
        "and resumable work while the roadmap owner remains focused on normative design.",
        "",
        ENGLISH_STATUS,
        "",
    ]
    status_body = status_lines[1:]
    while status_body and not status_body[0].strip():
        status_body.pop(0)
    if callouts:
        rendered.extend(["### Migrated implementation notes", ""])
        for index, block in enumerate(callouts):
            if index:
                rendered.append("")
            rendered.extend(block)
        rendered.append("")
    rendered.extend(status_body)
    text = "\n".join(rendered).rstrip() + "\n"
    return _rebase_links(
        text,
        source_relative=owner_relative,
        destination_relative=ledger_relative,
        repo_root=repo_root,
    )


def _verify_reconciled_ledger(existing: str, replacement: str, *, relative: str) -> None:
    """Reject replacement when it would drop prior history or migrated notes."""

    existing_history = {line for line in existing.splitlines() if HISTORY_ROW.match(line)}
    replacement_history = {line for line in replacement.splitlines() if HISTORY_ROW.match(line)}
    missing_history = existing_history - replacement_history
    existing_notes = {line for line in existing.splitlines() if line.startswith(">")}
    replacement_notes = {line for line in replacement.splitlines() if line.startswith(">")}
    missing_notes = existing_notes - replacement_notes
    if missing_history or missing_notes:
        raise ValueError(
            f"{relative}: existing ledger contains history or migrated notes absent from owner"
        )


def _normalize_status_lines(status_lines: list[str], *, owner_relative: str) -> list[str]:
    required = (
        "### Implementation scope",
        "### Implementation history",
        "### Remaining work",
    )
    if all(heading in status_lines for heading in required):
        return status_lines
    detail = status_lines[1:]
    while detail and not detail[0].strip():
        detail.pop(0)
    while detail and not detail[-1].strip():
        detail.pop()
    migrated_on = date.today().isoformat()
    return [
        ENGLISH_STATUS,
        "",
        "### Implementation scope",
        "",
        "| Area | State | Evidence | Notes |",
        "|------|-------|----------|-------|",
        "| Migrated legacy status | in-progress | Legacy status detail below | "
        "The prior owner did not use the structured ledger shape. |",
        "",
        "#### Migrated legacy status detail",
        "",
        *detail,
        "",
        "### Implementation history",
        "",
        "| Date | State | Change | Evidence | Remaining |",
        "|------|-------|--------|----------|-----------|",
        f"| {migrated_on} | in-progress | Migrated the legacy status into the delegated ledger "
        "without reconstructing earlier provenance. | current change; preserved owner status "
        f"from `{owner_relative}`. | Replace the legacy summary with bounded evidence-backed "
        "scope rows and observable exits. |",
        "",
        "### Remaining work",
        "",
        "- [ ] Replace the migrated legacy summary with bounded evidence-backed scope rows and "
        "observable remaining-work exits.",
    ]


def _missing_status_lines(owner_relative: str) -> list[str]:
    adopted_on = date.today().isoformat()
    return [
        ENGLISH_STATUS,
        "",
        "### Implementation scope",
        "",
        "| Area | State | Evidence | Notes |",
        "|------|-------|----------|-------|",
        "| Adopted unassessed scope | not-started | Owner design only | No implementation "
        "evidence was recorded when this ledger was adopted. |",
        "",
        "### Implementation history",
        "",
        "| Date | State | Change | Evidence | Remaining |",
        "|------|-------|--------|----------|-----------|",
        f"| {adopted_on} | not-started | Adopted the delegated ledger; earlier provenance was "
        f"not reconstructed. | current change; `{owner_relative}`. | Assess bounded source and "
        "test evidence before raising any scope state. |",
        "",
        "### Remaining work",
        "",
        "- [ ] Assess bounded source and focused-test evidence, then replace the unassessed scope "
        "with independently deliverable evidence-backed rows.",
    ]


def _plan_owner(
    repo_root: Path,
    owner_relative: str,
    *,
    allow_missing: bool = False,
    reconcile_existing: bool = False,
) -> tuple[OwnerMigration, dict[Path, str]] | None:
    owner_path = repo_root / owner_relative
    if not owner_path.is_file():
        raise ValueError(f"{owner_relative}: owner file does not exist")
    ledger_relative = _ledger_relative(owner_relative)
    ledger_path = repo_root / ledger_relative
    owner_text = owner_path.read_text(encoding="utf-8")
    expected_link = _relative_link(owner_relative, ledger_relative)
    has_status_callout = any(
        line.startswith("> **Implementation status") for line in owner_text.splitlines()
    )
    if ENGLISH_STATUS not in owner_text and not has_status_callout:
        if f"]({expected_link})" in owner_text and ledger_path.is_file():
            return None
        if not allow_missing:
            raise ValueError(f"{owner_relative}: owner is neither inline nor delegated")
    if ledger_path.exists() and not reconcile_existing:
        raise ValueError(f"{owner_relative}: ledger already exists: {ledger_relative}")

    original_owner_lines = owner_text.splitlines()
    if ENGLISH_STATUS in owner_text:
        owner_lines, status_lines = _remove_status_section(
            original_owner_lines,
            ENGLISH_STATUS,
            required=True,
            relative=owner_relative,
        )
        formal_status_lines = len(status_lines)
    else:
        owner_lines = original_owner_lines
        status_lines = (
            [ENGLISH_STATUS] if has_status_callout else _missing_status_lines(owner_relative)
        )
        formal_status_lines = 0
    owner_lines, callouts = _remove_status_callouts(owner_lines, "> **Implementation status")
    owner_lines = _add_related_link(
        owner_lines,
        heading=ENGLISH_RELATED,
        label="Delivery status and remaining work",
        link_label="Implementation ledger",
        link=expected_link,
        relative=owner_relative,
        aliases=ENGLISH_RELATED_ALIASES,
    )
    english = "\n".join(owner_lines).rstrip() + "\n"

    korean_relative = owner_relative[:-3] + "-ko.md"
    korean_path = repo_root / korean_relative
    if not korean_path.is_file():
        raise ValueError(f"{owner_relative}: missing Korean owner {korean_relative}")
    korean_lines = korean_path.read_text(encoding="utf-8").splitlines()
    korean_lines, korean_status = _remove_status_section(
        korean_lines,
        KOREAN_STATUS,
        required=False,
        relative=korean_relative,
    )
    korean_lines, korean_callouts = _remove_status_callouts(korean_lines, "> **구현 상태")
    korean_lines = _add_related_link(
        korean_lines,
        heading=KOREAN_RELATED,
        label="구현 상태 및 남은 작업",
        link_label="구현 원장",
        link=expected_link,
        relative=korean_relative,
        aliases=KOREAN_RELATED_ALIASES,
        normalize_alias=True,
    )
    korean = "\n".join(korean_lines).rstrip() + "\n"
    korean = _refresh_korean_metadata(korean, english, relative=korean_relative)

    ledger = _render_ledger(
        owner_relative=owner_relative,
        ledger_relative=ledger_relative,
        owner_lines=original_owner_lines,
        status_lines=status_lines,
        callouts=callouts,
        repo_root=repo_root,
    )
    if ledger_path.exists():
        _verify_reconciled_ledger(
            ledger_path.read_text(encoding="utf-8"),
            ledger,
            relative=ledger_relative,
        )
    migration = OwnerMigration(
        owner=owner_relative,
        ledger=ledger_relative,
        removed_english_lines=formal_status_lines + sum(len(block) for block in callouts),
        removed_korean_lines=len(korean_status) + sum(len(block) for block in korean_callouts),
    )
    return migration, {
        Path(owner_relative): english,
        Path(korean_relative): korean,
        Path(ledger_relative): ledger,
    }


def plan_migrations(
    repo_root: Path,
    owners: Iterable[str],
    *,
    allow_missing: bool = False,
    reconcile_existing: bool = False,
) -> MigrationPlan:
    migrations: list[OwnerMigration] = []
    writes: dict[Path, str] = {}
    for owner in owners:
        planned = _plan_owner(
            repo_root,
            owner,
            allow_missing=allow_missing,
            reconcile_existing=reconcile_existing,
        )
        if planned is None:
            continue
        migration, owner_writes = planned
        collisions = set(writes).intersection(owner_writes)
        if collisions:
            outputs = sorted(str(path) for path in collisions)
            raise ValueError(f"duplicate migration outputs: {outputs}")
        migrations.append(migration)
        writes.update(owner_writes)
    return MigrationPlan(tuple(migrations), writes)


def apply_plan(repo_root: Path, plan: MigrationPlan) -> None:
    for relative, content in plan.writes.items():
        path = repo_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def plan_status_link_repairs(repo_root: Path) -> dict[Path, str]:
    writes: dict[Path, str] = {}
    root = repo_root / LEDGER_ROOT
    if not root.is_dir():
        return writes
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(repo_root)
        content = path.read_text(encoding="utf-8")
        repaired = _rebase_links(
            content,
            source_relative=str(relative),
            destination_relative=str(relative),
            repo_root=repo_root,
        )
        if repaired != content:
            writes[relative] = repaired
    return writes


def _remove_ledger_only_related_duplicate(
    lines: list[str], *, headings: tuple[str, ...], expected_link: str, relative: str
) -> list[str]:
    matched = sorted(
        ((start, end) for heading in headings for start, end in _heading_ranges(lines, heading)),
        reverse=True,
    )
    if len(matched) <= 1:
        return lines
    removable = []
    for start, end in matched:
        section = "\n".join(lines[start:end])
        links = LINK_PATTERN.findall(section)
        if f"]({expected_link})" in section and len(links) == 1:
            removable.append((start, end))
    if len(removable) != 1:
        raise ValueError(f"{relative}: cannot identify one ledger-only Related section")
    start, end = removable[0]
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    return lines[:start] + lines[end:]


def plan_owner_structure_repairs(repo_root: Path) -> dict[Path, str]:
    writes: dict[Path, str] = {}
    for owner_path in sorted((repo_root / ROADMAP_ROOT).rglob("*.md")):
        if owner_path.name.endswith("-ko.md"):
            continue
        owner_relative = str(owner_path.relative_to(repo_root))
        if _is_exempt_owner(owner_relative):
            continue
        ledger_relative = _ledger_relative(owner_relative)
        ledger_path = repo_root / ledger_relative
        if not ledger_path.is_file():
            continue
        expected_link = _relative_link(owner_relative, ledger_relative)
        owner_text = owner_path.read_text(encoding="utf-8")
        if _heading_ranges(owner_text.splitlines(), ENGLISH_STATUS):
            continue

        owner_lines = owner_text.splitlines()
        if f"]({expected_link})" in owner_text:
            owner_lines = _remove_ledger_only_related_duplicate(
                owner_lines,
                headings=(ENGLISH_RELATED, *ENGLISH_RELATED_ALIASES),
                expected_link=expected_link,
                relative=owner_relative,
            )
        owner_lines, _ = _remove_status_callouts(owner_lines, "> **Implementation status")
        owner_lines = _add_related_link(
            owner_lines,
            heading=ENGLISH_RELATED,
            aliases=ENGLISH_RELATED_ALIASES,
            label="Delivery status and remaining work",
            link_label="Implementation ledger",
            link=expected_link,
            relative=owner_relative,
        )
        english = "\n".join(owner_lines).rstrip() + "\n"

        korean_relative = owner_relative[:-3] + "-ko.md"
        korean_path = repo_root / korean_relative
        korean_lines = korean_path.read_text(encoding="utf-8").splitlines()
        korean_lines, _ = _remove_status_section(
            korean_lines,
            KOREAN_STATUS,
            required=False,
            relative=korean_relative,
        )
        for status_heading in KOREAN_STATUS_ALIASES:
            korean_lines, _ = _remove_status_section(
                korean_lines,
                status_heading,
                required=False,
                relative=korean_relative,
            )
        korean_lines, _ = _remove_status_callouts(korean_lines, "> **구현 상태")
        if f"]({expected_link})" in "\n".join(korean_lines):
            korean_lines = _remove_ledger_only_related_duplicate(
                korean_lines,
                headings=(KOREAN_RELATED, *KOREAN_RELATED_ALIASES),
                expected_link=expected_link,
                relative=korean_relative,
            )
        korean_lines = _add_related_link(
            korean_lines,
            heading=KOREAN_RELATED,
            aliases=KOREAN_RELATED_ALIASES,
            normalize_alias=True,
            label="구현 상태 및 남은 작업",
            link_label="구현 원장",
            link=expected_link,
            relative=korean_relative,
        )
        korean = "\n".join(korean_lines).rstrip() + "\n"
        korean = _refresh_korean_metadata(korean, english, relative=korean_relative)

        if english != owner_text:
            writes[Path(owner_relative)] = english
        if korean != korean_path.read_text(encoding="utf-8"):
            writes[Path(korean_relative)] = korean
    return writes


def discover_inline_owners(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "docs/roadmap"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    owners: list[str] = []
    for relative in result.stdout.splitlines():
        path = PurePosixPath(relative)
        name = path.name.lower()
        if not relative.endswith(".md") or name.endswith("-ko.md"):
            continue
        if _is_exempt_owner(relative):
            continue
        content = (repo_root / relative).read_text(encoding="utf-8")
        if ENGLISH_STATUS in content or "> **Implementation status" in content:
            owners.append(relative)
    return sorted(owners)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owners", nargs="*", help="Canonical English roadmap owner paths")
    parser.add_argument("--all", action="store_true", help="Plan every remaining inline owner")
    parser.add_argument("--apply", action="store_true", help="Write the complete validated plan")
    parser.add_argument("--limit", type=int, help="Bound sorted --all owners for a pilot batch")
    parser.add_argument(
        "--repair-links",
        action="store_true",
        help="Redirect removed owner status anchors in existing ledgers",
    )
    parser.add_argument(
        "--adopt-missing",
        action="store_true",
        help="Create not-started ledgers for explicit owners with no prior status",
    )
    parser.add_argument(
        "--repair-owner-structure",
        action="store_true",
        help="Merge duplicate Related sections and remove status aliases",
    )
    parser.add_argument(
        "--reconcile-existing",
        action="store_true",
        help="Replace a stale mirrored ledger only when owner history is a strict superset",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.repair_owner_structure:
        if (
            args.all
            or args.owners
            or args.limit is not None
            or args.adopt_missing
            or args.reconcile_existing
        ):
            raise SystemExit("--repair-owner-structure cannot be combined with owner selection")
        writes = plan_owner_structure_repairs(REPO_ROOT)
        for relative in writes:
            print(relative)
        if args.apply:
            apply_plan(REPO_ROOT, MigrationPlan((), writes))
            print(f"roadmap-owner-structure-repair: APPLIED ({len(writes)} file(s))")
        else:
            print(f"roadmap-owner-structure-repair: DRY-RUN ({len(writes)} file(s))")
        return 0
    if args.repair_links:
        if (
            args.all
            or args.owners
            or args.limit is not None
            or args.adopt_missing
            or args.repair_owner_structure
            or args.reconcile_existing
        ):
            raise SystemExit("--repair-links cannot be combined with owner selection")
        writes = plan_status_link_repairs(REPO_ROOT)
        for relative in writes:
            print(relative)
        if args.apply:
            apply_plan(REPO_ROOT, MigrationPlan((), writes))
            print(f"roadmap-ledger-link-repair: APPLIED ({len(writes)} file(s))")
        else:
            print(f"roadmap-ledger-link-repair: DRY-RUN ({len(writes)} file(s))")
        return 0
    if args.all == bool(args.owners):
        raise SystemExit("choose exactly one of --all or explicit owner paths")
    if args.adopt_missing and args.all:
        raise SystemExit("--adopt-missing requires explicit owner paths")
    if args.reconcile_existing and args.all:
        raise SystemExit("--reconcile-existing requires explicit owner paths")
    owners = discover_inline_owners(REPO_ROOT) if args.all else args.owners
    if args.limit is not None:
        if not args.all or args.limit < 1:
            raise SystemExit("--limit requires --all and a positive value")
        owners = owners[: args.limit]
    try:
        plan = plan_migrations(
            REPO_ROOT,
            owners,
            allow_missing=args.adopt_missing,
            reconcile_existing=args.reconcile_existing,
        )
    except ValueError as error:
        print(f"roadmap-ledger-migration: ERROR: {error}")
        return 1
    for migration in plan.migrations:
        print(
            f"{migration.owner} -> {migration.ledger} "
            f"(removed en={migration.removed_english_lines}, ko={migration.removed_korean_lines})"
        )
    if args.apply:
        apply_plan(REPO_ROOT, plan)
        print(f"roadmap-ledger-migration: APPLIED ({len(plan.migrations)} owner(s))")
    else:
        print(f"roadmap-ledger-migration: DRY-RUN ({len(plan.migrations)} owner(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
