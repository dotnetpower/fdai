from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_module() -> ModuleType:
    path = REPO_ROOT / "scripts/automation/migrate-roadmap-implementation-ledgers.py"
    spec = importlib.util.spec_from_file_location("migrate_roadmap_ledgers", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_pair(repo: Path, *, korean_status: bool = True) -> str:
    owner = "docs/roadmap/architecture/example.md"
    owner_path = repo / owner
    owner_path.parent.mkdir(parents=True)
    owner_path.write_text(
        """# Example

> **Implementation status:** A migrated note with [design](other.md).
> The note continues.

## Design

Normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Loader | implemented | [source](../../../services/loader.py) | Complete. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-24 | implemented | Added loader. | current change | None. |

### Remaining work

- [x] Complete.

## Related docs

| To learn about | Read |
|----------------|------|
| Other design | [Other](other.md) |
""",
        encoding="utf-8",
    )
    (owner_path.parent / "other.md").write_text("# Other\n", encoding="utf-8")
    (repo / "services").mkdir()
    (repo / "services" / "loader.py").write_text("", encoding="utf-8")

    ko_path = owner_path.with_name("example-ko.md")
    status = (
        """
## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Loader | implemented | source | 완료. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-24 | implemented | Loader 추가. | current change | 없음. |

### 남은 작업

- [x] 완료.
"""
        if korean_status
        else ""
    )
    ko_path.write_text(
        """---
translation_of: example.md
translation_source_sha: stale
translation_revised: 2026-08-01
---
# 예제

> **구현 상태:** 이동할 중복 상태입니다.

## 설계

규범 설계입니다.
"""
        + status
        + """
## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 다른 설계 | [기타](other-ko.md) |
""",
        encoding="utf-8",
    )
    (owner_path.parent / "other-ko.md").write_text("# 기타\n", encoding="utf-8")
    return owner


def test_plan_moves_status_rebases_links_and_updates_korean(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path)

    plan = module.plan_migrations(tmp_path, [owner])

    assert len(plan.migrations) == 1
    assert not (tmp_path / "docs/roadmap-implementation/architecture/example.md").exists()

    english = plan.writes[Path(owner)]
    korean = plan.writes[Path(owner.replace(".md", "-ko.md"))]
    ledger_path = Path("docs/roadmap-implementation/architecture/example.md")
    ledger = plan.writes[ledger_path]

    assert "## Implementation status" not in english
    assert "Implementation status:**" not in english
    assert (
        "[Implementation ledger](../../roadmap-implementation/architecture/example.md)" in english
    )
    assert "## Implementation status" in ledger
    assert "### Migrated implementation notes" in ledger
    assert "[design](../../roadmap/architecture/other.md)" in ledger
    assert "[source](../../../services/loader.py)" in ledger
    assert "## 구현 상태" not in korean
    assert "**구현 상태:**" not in korean
    assert "[구현 원장](../../roadmap-implementation/architecture/example.md)" in korean
    assert "translation_source_sha: stale" not in korean


def test_apply_is_idempotent_and_accepts_missing_korean_status(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path, korean_status=False)

    plan = module.plan_migrations(tmp_path, [owner])
    module.apply_plan(tmp_path, plan)

    second = module.plan_migrations(tmp_path, [owner])

    assert second.migrations == ()
    assert second.writes == {}


def test_plan_fails_before_writing_on_ambiguous_status_sections(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path)
    owner_path = tmp_path / owner
    owner_path.write_text(
        owner_path.read_text(encoding="utf-8") + "\n## Implementation status\n",
        encoding="utf-8",
    )

    try:
        module.plan_migrations(tmp_path, [owner])
    except ValueError as error:
        assert "exactly one" in str(error)
    else:
        raise AssertionError("ambiguous status sections must fail closed")

    assert not (tmp_path / "docs/roadmap-implementation/architecture/example.md").exists()


def test_reconcile_existing_preserves_history_and_cuts_over_owner(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path)
    initial = module.plan_migrations(tmp_path, [owner])
    ledger_path = Path("docs/roadmap-implementation/architecture/example.md")
    ledger = tmp_path / ledger_path
    ledger.parent.mkdir(parents=True)
    ledger.write_text(initial.writes[ledger_path], encoding="utf-8")
    owner_path = tmp_path / owner
    owner_text = owner_path.read_text(encoding="utf-8")
    owner_path.write_text(
        owner_text.replace(
            "### Remaining work",
            "| 2026-08-25 | implemented | Added follow-up. | current change | None. |\n\n"
            "### Remaining work",
        ),
        encoding="utf-8",
    )

    plan = module.plan_migrations(tmp_path, [owner], reconcile_existing=True)

    replacement = plan.writes[ledger_path]
    assert "| 2026-08-24 | implemented | Added loader." in replacement
    assert "| 2026-08-25 | implemented | Added follow-up." in replacement
    assert "## Implementation status" not in plan.writes[Path(owner)]


def test_reconcile_existing_rejects_history_loss(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path)
    ledger_path = tmp_path / "docs/roadmap-implementation/architecture/example.md"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        "# Example implementation ledger\n\n"
        "## Implementation status\n\n"
        "### Implementation history\n\n"
        "| Date | State | Change | Evidence | Remaining |\n"
        "|------|-------|--------|----------|-----------|\n"
        "| 2026-08-23 | implemented | Prior unique row. | old evidence | None. |\n",
        encoding="utf-8",
    )

    try:
        module.plan_migrations(tmp_path, [owner], reconcile_existing=True)
    except ValueError as error:
        assert "absent from owner" in str(error)
    else:
        raise AssertionError("reconciliation must reject append-only history loss")


def test_merge_existing_preserves_disjoint_ledger_records(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path)
    initial = module.plan_migrations(tmp_path, [owner])
    ledger_path = Path("docs/roadmap-implementation/architecture/example.md")
    ledger = tmp_path / ledger_path
    ledger.parent.mkdir(parents=True)
    existing = initial.writes[ledger_path]
    existing = (
        existing.replace(
            "### Implementation scope",
            "### Migrated implementation notes\n\n"
            "> Prior delegated note.\n\n"
            "### Implementation scope",
        )
        .replace(
            "### Implementation history",
            "| Prior delegated area | implemented | prior.py | Preserved. |\n\n"
            "### Implementation history",
        )
        .replace(
            "### Remaining work",
            "| 2026-08-23 | implemented | Prior delegated change. | prior evidence | None. |\n\n"
            "### Remaining work",
        )
        .replace(
            "- [x] Complete.",
            "- [x] Complete.\n- [ ] Retain prior runtime evidence.",
        )
    )
    ledger.write_text(existing, encoding="utf-8")
    owner_path = tmp_path / owner
    owner_path.write_text(
        owner_path.read_text(encoding="utf-8").replace(
            "### Remaining work",
            "| 2026-08-25 | implemented | Added follow-up. | current change | None. |\n\n"
            "### Remaining work",
        ),
        encoding="utf-8",
    )

    plan = module.plan_migrations(tmp_path, [owner], merge_existing=True)

    replacement = plan.writes[ledger_path]
    assert "> Prior delegated note." in replacement
    assert "| Prior delegated area | implemented | prior.py | Preserved. |" in replacement
    assert "| 2026-08-23 | implemented | Prior delegated change." in replacement
    assert "| 2026-08-25 | implemented | Added follow-up." in replacement
    assert "- [ ] Retain prior runtime evidence." in replacement
    assert "## Implementation status" not in plan.writes[Path(owner)]


def test_plan_normalizes_legacy_unstructured_status(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path, korean_status=False)
    owner_path = tmp_path / owner
    content = owner_path.read_text(encoding="utf-8")
    start = content.index("## Implementation status")
    end = content.index("## Related docs")
    owner_path.write_text(
        content[:start]
        + "## Implementation status\n\nLegacy status summary with source evidence.\n\n"
        + content[end:],
        encoding="utf-8",
    )

    plan = module.plan_migrations(tmp_path, [owner])
    ledger = plan.writes[Path("docs/roadmap-implementation/architecture/example.md")]

    assert "### Implementation scope" in ledger
    assert "| Migrated legacy status | in-progress |" in ledger
    assert "#### Migrated legacy status detail" in ledger
    assert "Legacy status summary with source evidence." in ledger
    assert "### Implementation history" in ledger
    assert "### Remaining work" in ledger


def test_plan_migrates_callout_only_owner(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path, korean_status=False)
    owner_path = tmp_path / owner
    content = owner_path.read_text(encoding="utf-8")
    start = content.index("## Implementation status")
    end = content.index("## Related docs")
    owner_path.write_text(content[:start] + content[end:], encoding="utf-8")

    plan = module.plan_migrations(tmp_path, [owner])
    english = plan.writes[Path(owner)]
    ledger = plan.writes[Path("docs/roadmap-implementation/architecture/example.md")]

    assert "Implementation status:**" not in english
    assert "### Migrated implementation notes" in ledger
    assert "A migrated note" in ledger
    assert "### Implementation scope" in ledger
    assert "### Implementation history" in ledger
    assert "### Remaining work" in ledger


def test_explicit_adoption_of_missing_ledger_starts_not_started(tmp_path: Path) -> None:
    module = _load_module()
    owner = _write_pair(tmp_path, korean_status=False)
    owner_path = tmp_path / owner
    content = owner_path.read_text(encoding="utf-8")
    start = content.index("> **Implementation status:")
    end = content.index("## Design")
    content = content[:start] + content[end:]
    start = content.index("## Implementation status")
    end = content.index("## Related docs")
    owner_path.write_text(content[:start] + content[end:], encoding="utf-8")

    plan = module.plan_migrations(tmp_path, [owner], allow_missing=True)
    ledger = plan.writes[Path("docs/roadmap-implementation/architecture/example.md")]

    assert "| Adopted unassessed scope | not-started |" in ledger
    assert "earlier provenance was not reconstructed" in ledger


def test_related_docs_list_keeps_its_shape() -> None:
    module = _load_module()
    lines = ["# Owner", "", "## 관련 문서", "", "- [기타](other-ko.md)"]

    migrated = module._add_related_link(
        lines,
        heading="## 관련 문서",
        label="구현 상태 및 남은 작업",
        link_label="구현 원장",
        link="../../roadmap-implementation/interfaces/owner.md",
        relative="docs/roadmap/interfaces/owner-ko.md",
    )

    assert (
        "- [구현 원장](../../roadmap-implementation/interfaces/owner.md) - 구현 상태 및 남은 작업"
        in migrated
    )
    assert "- [기타](other-ko.md)" in migrated


def test_related_heading_alias_is_reused_without_duplicate_section() -> None:
    module = _load_module()
    lines = [
        "# Owner",
        "",
        "## Related documents",
        "",
        "| To learn about | Read |",
        "|----------------|------|",
        "| Other | [Other](other.md) |",
    ]

    migrated = module._add_related_link(
        lines,
        heading="## Related docs",
        aliases=("## Related documents", "## Related Documents", "## Related"),
        label="Delivery status and remaining work",
        link_label="Implementation ledger",
        link="../../roadmap-implementation/interfaces/owner.md",
        relative="docs/roadmap/interfaces/owner.md",
    )

    assert migrated.count("## Related documents") == 1
    assert "## Related docs" not in migrated
    assert "[Implementation ledger]" in "\n".join(migrated)


def test_owner_structure_repair_adds_a_missing_delegated_link(tmp_path: Path) -> None:
    module = _load_module()
    owner = tmp_path / "docs/roadmap/architecture/example.md"
    owner.parent.mkdir(parents=True)
    owner.write_text(
        "# Example\n\n## Related docs\n\n- [Other](other.md)\n",
        encoding="utf-8",
    )
    korean = owner.with_name("example-ko.md")
    korean.write_text(
        """---
translation_of: example.md
translation_source_sha: stale
translation_revised: 2026-08-01
---
# 예제

## 관련 문서

- [기타](other-ko.md)
""",
        encoding="utf-8",
    )
    ledger = tmp_path / "docs/roadmap-implementation/architecture/example.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# Example implementation ledger\n", encoding="utf-8")

    writes = module.plan_owner_structure_repairs(tmp_path)

    repaired_owner = writes[Path("docs/roadmap/architecture/example.md")]
    repaired_korean = writes[Path("docs/roadmap/architecture/example-ko.md")]
    expected_link = "../../roadmap-implementation/architecture/example.md"
    assert f"[Implementation ledger]({expected_link})" in repaired_owner
    assert f"[구현 원장]({expected_link})" in repaired_korean
    assert "translation_source_sha: stale" not in repaired_korean


def test_owner_structure_repair_skips_roadmap_indexes(tmp_path: Path) -> None:
    module = _load_module()
    roadmap = tmp_path / "docs/roadmap"
    roadmap.mkdir(parents=True)
    (roadmap / "README.md").write_text("# Roadmap\n", encoding="utf-8")
    (roadmap / "README-ko.md").write_text("# 로드맵\n", encoding="utf-8")
    ledger = tmp_path / "docs/roadmap-implementation/README.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# Ledgers\n", encoding="utf-8")

    assert module.plan_owner_structure_repairs(tmp_path) == {}


def test_rebase_redirects_owner_status_anchor_to_mirrored_ledger(tmp_path: Path) -> None:
    module = _load_module()
    owner = tmp_path / "docs/roadmap/architecture/example.md"
    target = owner.with_name("other.md")
    owner.parent.mkdir(parents=True)
    owner.write_text("# Example\n", encoding="utf-8")
    target.write_text("# Other\n\n## Implementation status\n", encoding="utf-8")

    rebased = module._rebase_links(
        "[Other status](other.md#implementation-status)",
        source_relative="docs/roadmap/architecture/example.md",
        destination_relative="docs/roadmap-implementation/architecture/example.md",
        repo_root=tmp_path,
    )

    assert rebased == "[Other status](other.md#implementation-status)"
