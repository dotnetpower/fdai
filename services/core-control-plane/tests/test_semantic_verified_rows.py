"""A verified result without a reviewed presentation shows its rows as an evidence table."""

from __future__ import annotations

from fdai_core_service.semantic_verified_rows import verified_rows_table


def _output(*values: dict[str, object]) -> dict[str, object]:
    return {"rows": [{"row_id": f"r{index}", "values": item} for index, item in enumerate(values)]}


def test_a_compiled_count_shows_its_verified_value() -> None:
    lines = verified_rows_table(_output({"operation": "count", "value": 27}), korean=False)

    assert lines[1:] == ["| operation | value |", "|---|---|", "| count | 27 |"]


def test_named_rows_lead_with_display_fields_and_keep_identity_in_details() -> None:
    lines = verified_rows_table(
        _output(
            {
                "id": "scope-1/resource-group/rg-a/providers/x/y",
                "name": "ca-core",
                "type": "compute.container-app",
                "status": "Running",
                "object_type": "Resource",
            }
        ),
        korean=False,
    )

    assert lines[1] == "| name | type | status |"
    assert lines[3] == "| ca-core | compute.container-app | Running |"
    assert all("scope-1" not in line for line in lines)


def test_rows_beyond_the_bound_are_counted_and_cells_cannot_break_the_table() -> None:
    rows = [
        {"name": f"vm|{index}", "group": {"kind": "type", "value": "vm"}} for index in range(23)
    ]
    lines = verified_rows_table(_output(*rows), korean=True)

    assert lines[3] == "| vm\\|0 | kind=type, value=vm |"
    assert lines[-1] == "- 표에 표시하지 않은 검증된 행 3개는 기술 상세에 있습니다."
    assert sum(1 for line in lines if line.startswith("| vm")) == 20


def test_an_output_without_rows_adds_nothing() -> None:
    assert verified_rows_table({"rows": []}, korean=False) == []
    assert verified_rows_table({}, korean=True) == []


def test_a_long_value_is_named_not_cut_and_the_table_stays_bounded() -> None:
    rows = [{"name": "x" * 10_000, "type": "compute.vm"} for _ in range(80)]
    lines = verified_rows_table(_output(*rows), korean=False)

    assert lines[3] == "| (see technical details) | compute.vm |"
    assert sum(len(line) for line in lines) < 4_200
    assert lines[-1] == "- 60 more verified rows are in technical details."


def test_stated_notices_lead_the_answer_and_restate_only_the_read() -> None:
    from fdai_core_service.semantic_verified_rows import with_stated_notices

    answer = "## 검증된 결과\n\n- 전체 1개 행 중 1개를 검증했습니다."
    korean = with_stated_notices(
        answer, ("cause.not_established", "window.default.86400"), locale="ko"
    )
    english = with_stated_notices(
        "## Verified result\n\n- rows", ("window.applied.259200",), locale="en"
    )

    lines = korean.splitlines()
    assert lines[0] == "## 검증된 결과"
    assert lines[2].startswith("- 원인은 확정하지 않았습니다.")
    assert lines[3] == "- 조회 기간: 기간을 밝히지 않아 적용한 기본값인 최근 1일"
    assert "Read window: the last 3 days, as stated." in english
    # A frame without a reviewed notice requirement leaves the answer untouched.
    assert with_stated_notices(answer, ("governed_documents.optional",), locale="ko") == answer
    unproven = with_stated_notices(answer, ("anchor.uniqueness_unproven",), locale="en")
    assert "another resource with the same name may not be reflected yet" in unproven


def test_measure_fields_the_frame_reads_lead_the_table_before_receipt_fields() -> None:
    from fdai_core_service.semantic_verified_rows import verified_rows_table

    output = {
        "rows": [
            {
                "values": {
                    "assessment_scope": "exact_target_only",
                    "execution_authority": False,
                    "inventory_read_at": "2026-09-29T20:14:12+00:00",
                    "name": "aks-app",
                    "provisioning_status": "Succeeded",
                    "related_resources_assessed": False,
                    "running_status": "Stopped",
                    "target_state_assessment": "observed_not_running",
                }
            }
        ]
    }

    lines = verified_rows_table(
        output, korean=False, leading=("provisioning_status", "running_status", "revision_name")
    )

    header = [cell.strip() for cell in lines[1].strip("|").split("|")]
    assert header[:3] == ["name", "provisioning_status", "running_status"]
    assert "Stopped" in lines[3]
