"""Generated Python task validation tests."""

from fdai.core.python_task import validate_python_task
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
)


def _task(source: str, **overrides: object) -> PythonTaskSpec:
    values = {
        "task_id": "gpu.health-check",
        "version": "1.0.0",
        "entrypoint": "main.py",
        "files": (PythonTaskFile(path="main.py", content=source),),
        "required_modules": (),
        "capabilities": frozenset(),
    }
    values.update(overrides)
    return PythonTaskSpec(**values)  # type: ignore[arg-type]


def test_valid_multifile_gpu_task_is_content_addressed() -> None:
    task = _task(
        "import json\nimport torch\nprint(json.dumps({'cuda': torch.cuda.is_available()}))\n",
        required_modules=("torch",),
        capabilities=frozenset({PythonTaskCapability.GPU}),
        files=(
            PythonTaskFile(
                path="main.py",
                content=(
                    "import json\nimport torch\n"
                    "print(json.dumps({'cuda': torch.cuda.is_available()}))\n"
                ),
            ),
            PythonTaskFile(path="config/default.json", content='{"batch_size": 4}\n'),
        ),
    )

    report = validate_python_task(task)

    assert report.valid
    assert report.artifact_hash == task.artifact_hash
    assert report.detected_capabilities == frozenset({PythonTaskCapability.GPU})
    assert report.imported_modules == ("json", "torch")


def test_validator_rejects_traversal_dynamic_code_and_undeclared_capabilities() -> None:
    task = _task(
        "import requests\nexec('print(1)')\n",
        files=(
            PythonTaskFile(path="main.py", content="import requests\nexec('print(1)')\n"),
            PythonTaskFile(path="../escape.txt", content="blocked"),
        ),
    )

    report = validate_python_task(task)

    assert not report.valid
    assert {issue.code for issue in report.issues} >= {
        "invalid_path",
        "dynamic_code",
        "undeclared_capability",
        "undeclared_module",
    }


def test_hash_changes_with_source_but_not_file_order() -> None:
    first = _task(
        "print('a')\n",
        files=(
            PythonTaskFile(path="main.py", content="print('a')\n"),
            PythonTaskFile(path="data.json", content="{}\n"),
        ),
    )
    reordered = _task(
        "print('a')\n",
        files=tuple(reversed(first.files)),
    )
    changed = _task("print('b')\n")

    assert first.artifact_hash == reordered.artifact_hash
    assert first.artifact_hash != changed.artifact_hash


def test_sibling_module_and_filesystem_modes_are_classified() -> None:
    task = _task(
        "import helpers\nhelpers.load()\nopen('result.json', 'w').write('{}')\n",
        files=(
            PythonTaskFile(
                path="main.py",
                content="import helpers\nhelpers.load()\nopen('result.json', 'w').write('{}')\n",
            ),
            PythonTaskFile(path="helpers.py", content="def load():\n    return 1\n"),
        ),
        capabilities=frozenset({PythonTaskCapability.FILESYSTEM_WRITE}),
    )

    report = validate_python_task(task)

    assert report.valid
    assert "helpers" in report.imported_modules
    assert report.detected_capabilities == frozenset({PythonTaskCapability.FILESYSTEM_WRITE})


def test_process_capability_is_forbidden_even_when_declared() -> None:
    task = _task(
        "import subprocess\nsubprocess.run(['az', 'account', 'show'], check=True)\n",
        capabilities=frozenset({PythonTaskCapability.PROCESS}),
    )

    report = validate_python_task(task)

    assert not report.valid
    assert "process_capability_forbidden" in {issue.code for issue in report.issues}
    assert report.detected_capabilities == frozenset({PythonTaskCapability.PROCESS})


def test_unused_process_capability_is_forbidden() -> None:
    task = _task(
        "print('no child process')\n",
        capabilities=frozenset({PythonTaskCapability.PROCESS}),
    )

    report = validate_python_task(task)

    assert not report.valid
    assert "process_capability_forbidden" in {issue.code for issue in report.issues}
