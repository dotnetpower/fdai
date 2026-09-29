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
