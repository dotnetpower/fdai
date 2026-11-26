"""Grounded code extraction remains bounded and never executes source."""

from fdai.core.python_task.grounded_code import (
    GroundedCodePolicy,
    extract_grounded_code,
)


def test_extracts_python_with_stable_hash_and_static_validation() -> None:
    answer = "Result:\n\n```python\nprint('ok')\n```"

    first = extract_grounded_code(answer)
    second = extract_grounded_code(answer)

    assert len(first) == 1
    assert first == second
    assert first[0].artifact_ref == f"code:sha256:{first[0].sha256}"
    assert first[0].content == "print('ok')\n"
    assert first[0].validation_status == "valid"
    assert first[0].validation_detail is None


def test_reports_python_syntax_error_without_running_source() -> None:
    artifacts = extract_grounded_code("```py\nraise SystemExit('must not run'\n```")

    assert artifacts[0].validation_status == "invalid"
    assert artifacts[0].validation_detail is not None
    assert artifacts[0].validation_detail.startswith("line 1:")


def test_non_python_code_is_grounded_but_not_claimed_as_validated() -> None:
    artifacts = extract_grounded_code("```yaml\nmode: shadow\n```")

    assert artifacts[0].language == "yaml"
    assert artifacts[0].validation_status == "not_checked"


def test_chart_presentation_fence_is_not_duplicated_as_code_evidence() -> None:
    answer = (
        '```chart\n{"type":"bar","data":[{"label":"db","value":2}]}\n```\n'
        "```python\nprint('still code')\n```"
    )

    artifacts = extract_grounded_code(answer)

    assert len(artifacts) == 1
    assert artifacts[0].language == "python"
    assert artifacts[0].content == "print('still code')\n"


def test_skips_oversized_artifacts_and_caps_count() -> None:
    policy = GroundedCodePolicy(
        max_artifacts=1,
        max_artifact_bytes=12,
        max_total_bytes=12,
    )
    answer = "```python\n" + ("x" * 20) + "\n```\n```python\npass\n```\n```python\nprint(1)\n```"

    artifacts = extract_grounded_code(answer, policy=policy)

    assert len(artifacts) == 1
    assert artifacts[0].content == "pass\n"


def test_ignores_unterminated_fence() -> None:
    assert extract_grounded_code("```python\nprint('partial')") == ()
