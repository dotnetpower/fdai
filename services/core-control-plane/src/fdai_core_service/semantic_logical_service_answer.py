"""Render verified logical-service topology and component state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_OUTPUT_SHAPE = "logical_service_current_state"
_RESOURCE_NODE_ID = "logical-service-resources"
_STATE_NODE_ID = "logical-service-resource-states"


def render_logical_service_current_state_answer(
    outputs: Sequence[Mapping[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Render one exact service path, or decline malformed and unrelated outputs."""

    if output_shape != _OUTPUT_SHAPE:
        return None
    indexed = {
        node_id: output for output in outputs if isinstance((node_id := output.get("node_id")), str)
    }
    service_output = indexed.get("logical-business-services") or indexed.get(
        "logical-service-target"
    )
    workload_output = indexed.get("logical-service-workloads") or indexed.get(
        "logical-service-target"
    )
    resource_output = indexed.get(_RESOURCE_NODE_ID)
    state_output = indexed.get(_STATE_NODE_ID)
    if (
        service_output is None
        or workload_output is None
        or resource_output is None
        or state_output is None
    ):
        return None
    services = _object_rows(service_output, object_type="BusinessService")
    workloads = _object_rows(workload_output, object_type="Workload")
    resources = _object_rows(resource_output, object_type="Resource")
    states = _state_rows(state_output)
    if services is None or workloads is None or resources is None or states is None:
        return None

    lines = [
        "## 논리 서비스 런타임 상태" if korean else "## Logical service runtime state",
        "",
    ]
    lines.extend(
        _object_lines(
            services,
            korean=korean,
            korean_label="비즈니스 서비스",
            english_label="Business service",
            korean_empty="확인 범위에서 매핑된 비즈니스 서비스가 없습니다.",
            english_empty="No mapped business service is present in the verified scope.",
        )
    )
    lines.extend(
        _object_lines(
            workloads,
            korean=korean,
            korean_label="워크로드",
            english_label="Workload",
            korean_empty="확인 범위에서 매핑된 워크로드가 없습니다.",
            english_empty="No mapped workload is present in the verified scope.",
        )
    )
    lines.extend(
        _object_lines(
            resources,
            korean=korean,
            korean_label="런타임 리소스",
            english_label="Runtime resource",
            korean_empty="확인 범위에서 매핑된 런타임 리소스가 없습니다.",
            english_empty="No mapped runtime resource is present in the verified scope.",
            include_type=True,
        )
    )
    lines.extend(["", "### 관측된 구성요소 상태" if korean else "### Observed component state", ""])
    if states:
        for state in states:
            lines.append(
                (
                    f"- `{state['name']}`: `{state['state']}` "
                    f"(`{state['type']}`, 관측 {state['observed_at']})"
                )
                if korean
                else (
                    f"- `{state['name']}`: `{state['state']}` "
                    f"(`{state['type']}`, observed {state['observed_at']})"
                )
            )
    else:
        lines.append(
            "- 최신 검증된 구성요소 상태를 확인할 수 없습니다."
            if korean
            else "- No fresh verified component state is available."
        )

    complete = all(
        output.get("source_complete") is True
        for output in (service_output, workload_output, resource_output, state_output)
    )
    lines.extend(
        [
            "",
            (
                f"- 매핑 범위: 서비스 `{len(services)}`개, 워크로드 `{len(workloads)}`개, "
                f"리소스 `{len(resources)}`개"
                if korean
                else (
                    f"- Mapping coverage: `{len(services)}` service(s), "
                    f"`{len(workloads)}` workload(s), `{len(resources)}` resource(s)"
                )
            ),
            (
                f"- 근거 완전성: `{'complete' if complete else 'incomplete'}`"
                if korean
                else f"- Evidence completeness: `{'complete' if complete else 'incomplete'}`"
            ),
        ]
    )
    limitations = tuple(
        dict.fromkeys(
            reason
            for output in (service_output, workload_output, resource_output, state_output)
            if isinstance((reason := output.get("source_truncation_reason")), str) and reason
        )
    )
    for reason in limitations:
        lines.append(f"- 제한 사항: `{reason}`" if korean else f"- Limitation: `{reason}`")
    lines.extend(
        [
            "",
            (
                "이 결과는 구성요소별 관측 상태만 보여 줍니다. 전체 서비스 건강도나 원인을 "
                "추론하지 않으며 `execution_authority=false`입니다."
                if korean
                else (
                    "This result reports component observations only. It does not infer aggregate "
                    "service health or cause, and `execution_authority=false`."
                )
            ),
        ]
    )
    return "\n".join(lines)


def _object_rows(
    output: Mapping[str, object],
    *,
    object_type: str,
) -> list[dict[str, str]] | None:
    raw_rows = output.get("rows")
    if not isinstance(raw_rows, list):
        return None
    rows: list[dict[str, str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping) or not isinstance(
            (values := raw_row.get("values")), Mapping
        ):
            return None
        object_id = values.get("id")
        properties = values.get("properties")
        if (
            values.get("object_type") != object_type
            or not isinstance(object_id, str)
            or not object_id
            or not isinstance(properties, Mapping)
        ):
            return None
        name = properties.get("name")
        runtime_type = properties.get("type")
        rows.append(
            {
                "id": object_id,
                "name": name if isinstance(name, str) and name else object_id,
                "type": (
                    runtime_type if isinstance(runtime_type, str) and runtime_type else "unknown"
                ),
            }
        )
    return rows


def _state_rows(output: Mapping[str, object]) -> list[dict[str, str]] | None:
    raw_rows = output.get("rows")
    if not isinstance(raw_rows, list):
        return None
    rows: list[dict[str, str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping) or not isinstance(
            (values := raw_row.get("values")), Mapping
        ):
            return None
        name = values.get("name")
        runtime_type = values.get("type")
        state = values.get("observed_state")
        observed_at = values.get("source_observed_at")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(runtime_type, str)
            or not runtime_type
            or not isinstance(state, str)
            or not state
            or not isinstance(observed_at, str)
            or not observed_at
            or values.get("execution_authority") is not False
        ):
            return None
        rows.append(
            {
                "name": name,
                "type": runtime_type,
                "state": state,
                "observed_at": observed_at,
            }
        )
    return rows


def _object_lines(
    rows: Sequence[Mapping[str, str]],
    *,
    korean: bool,
    korean_label: str,
    english_label: str,
    korean_empty: str,
    english_empty: str,
    include_type: bool = False,
) -> list[str]:
    if not rows:
        return [f"- {korean_empty if korean else english_empty}"]
    label = korean_label if korean else english_label
    return [
        (
            f"- {label}: `{row['name']}` (`{row['type']}`)"
            if include_type
            else f"- {label}: `{row['name']}` (`{row['id']}`)"
        )
        for row in rows
    ]


__all__ = ["render_logical_service_current_state_answer"]
