"""Azure OpenAI adapters - real T1/T2 model clients.

These modules live in ``delivery/`` per the module-boundaries rule
(see ``docs/roadmap/project-structure.md § Module Boundaries``):
they are wire-level HTTP clients (`httpx`), so `core/` MUST NOT import
from here. Composition-root loads them only when
``AppConfig.llm.mode == "azure"``.

The two exported classes implement Protocols defined in `core/`:

- :class:`~aiopspilot.core.tiers.t1_lightweight.tier.EmbeddingModel`
- :class:`~aiopspilot.core.quality_gate.gate.CrossCheckModel`

Every request is authenticated with an OIDC token issued by the
:class:`~aiopspilot.shared.providers.workload_identity.WorkloadIdentity`
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

from aiopspilot.delivery.azure.llm.critic import (
    AzureOpenAICriticModel,
    AzureOpenAICriticModelConfig,
)
from aiopspilot.delivery.azure.llm.cross_check import (
    AzureOpenAICrossCheckModel,
    AzureOpenAICrossCheckModelConfig,
)
from aiopspilot.delivery.azure.llm.embeddings import (
    AzureOpenAIEmbeddingModel,
    AzureOpenAIEmbeddingModelConfig,
)
from aiopspilot.delivery.azure.llm.judge import (
    AzureOpenAIJudgeModel,
    AzureOpenAIJudgeModelConfig,
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
]
