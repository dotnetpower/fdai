"""Azure OpenAI adapters - real T1/T2 model clients.

These modules live in ``delivery/`` per the module-boundaries rule
(see ``docs/roadmap/project-structure.md § Module Boundaries``):
they are wire-level HTTP clients (`httpx`), so `core/` MUST NOT import
from here. Composition-root loads them only when
``AppConfig.llm.mode == "azure"``.

The two exported classes implement Protocols defined in `core/`:

- :class:`~fdai.core.tiers.t1_lightweight.tier.EmbeddingModel`
- :class:`~fdai.core.quality_gate.gate.CrossCheckModel`

Every request is authenticated with an OIDC token issued by the
:class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
seam, so the composition root supplies either the Managed-Identity
adapter (prod) or the deterministic-local adapter (dev) - same code path.

Structured output
-----------------

Cross-check calls demand JSON output via ``response_format={"type":
"json_object"}`` so the quality-gate can parse without regex. The
adapter refuses (raises) on non-JSON responses; this is intentional -
"loose" model output is a hard error under phase-2 § Quality Gate.
"""

from __future__ import annotations

from fdai.delivery.azure.llm.critic import (
    AzureOpenAICriticModel,
    AzureOpenAICriticModelConfig,
)
from fdai.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from fdai.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from fdai.delivery.azure.llm.judge import (
    AzureOpenAIJudgeModel,
    AzureOpenAIJudgeModelConfig,
)
from fdai.delivery.azure.llm.rca_model import (
    AzureOpenAIRcaModel,
    AzureOpenAIRcaModelConfig,
)
from fdai.delivery.azure.llm.rubric import (
    AzureOpenAIRubricEvaluator,
    AzureOpenAIRubricEvaluatorConfig,
)

__all__ = [
    "AzureOpenAICriticModel",
    "AzureOpenAICriticModelConfig",
    "AzureOpenAICrossCheckModel",
    "AzureOpenAICrossCheckModelConfig",
    "AzureOpenAIEmbeddingModel",
    "AzureOpenAIEmbeddingModelConfig",
    "AzureOpenAIJudgeModel",
    "AzureOpenAIJudgeModelConfig",
    "AzureOpenAIRcaModel",
    "AzureOpenAIRcaModelConfig",
    "AzureOpenAIRubricEvaluator",
    "AzureOpenAIRubricEvaluatorConfig",
]
