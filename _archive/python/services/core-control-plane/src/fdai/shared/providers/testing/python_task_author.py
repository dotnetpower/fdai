"""Deterministic Python task author for local development."""

from __future__ import annotations

from fdai.shared.providers.python_task_author import PythonTaskAuthorRequest
from fdai.shared.providers.vm_task import (
    PythonTaskCapability,
    PythonTaskFile,
    PythonTaskSpec,
)


class TemplatePythonTaskAuthor:
    """Produce an editable capability-aware starter without model I/O."""

    async def author(self, request: PythonTaskAuthorRequest) -> PythonTaskSpec:
        if PythonTaskCapability.GPU in request.target_capabilities:
            modules = tuple(module for module in request.allowed_modules if module == "torch")
            modules = modules or ("torch",)
            source = (
                "import json\nimport torch\n\n"
                "result = {\n"
                "    'cuda_available': torch.cuda.is_available(),\n"
                "    'device_count': torch.cuda.device_count(),\n"
                "}\n"
                "print(json.dumps(result, sort_keys=True))\n"
            )
            capabilities = frozenset({PythonTaskCapability.GPU})
        else:
            modules = ()
            source = "import json\nprint(json.dumps({'status': 'ok'}))\n"
            capabilities = frozenset()
        return PythonTaskSpec(
            task_id=request.task_id_hint,
            version="1.0.0",
            entrypoint="main.py",
            files=(PythonTaskFile(path="main.py", content=source),),
            required_modules=modules,
            capabilities=capabilities,
            timeout_seconds=300,
        )


__all__ = ["TemplatePythonTaskAuthor"]
