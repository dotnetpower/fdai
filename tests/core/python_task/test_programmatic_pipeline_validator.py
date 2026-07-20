from __future__ import annotations

import pytest

from fdai.core.python_task.validator import validate_programmatic_pipeline_source


def test_allows_safe_data_operations_and_generated_client() -> None:
    source = """
import json
import statistics
from fdai_pipeline_client import PipelineClient

def main(client: PipelineClient, inputs: list[object]) -> object:
    values = [item["value"] for item in inputs]
    return {"mean": statistics.mean(values), "encoded": json.dumps(values)}
"""

    report = validate_programmatic_pipeline_source(source)

    assert report.valid
    assert report.imported_modules == ("fdai_pipeline_client", "json", "statistics")


@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("import os\n", "forbidden_import"),
        ("import azure.identity\n", "forbidden_import"),
        ("import subprocess\nsubprocess.run(['true'])\n", "forbidden_import"),
        ("import socket\nsocket.socket()\n", "forbidden_import"),
        ("open('/etc/passwd').read()\n", "forbidden_runtime_access"),
        ("eval('1 + 1')\n", "dynamic_code"),
        ("client.run_pipeline({})\n", "recursive_pipeline"),
        ("import fdai_pipeline_client\n", "forbidden_client_import"),
        ("client._token\n", "forbidden_introspection"),
        ("__builtins__['__import__']('os')\n", "forbidden_introspection"),
    ],
)
def test_blocks_programmatic_pipeline_escape_surfaces(source: str, code: str) -> None:
    report = validate_programmatic_pipeline_source(source)

    assert code in {issue.code for issue in report.issues}
