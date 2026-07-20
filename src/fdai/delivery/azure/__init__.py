"""Azure adapters.

Azure is the implemented CSP target (see
[Implementation Focus](../../../../.github/copilot-instructions.md#implementation-focus-must)).
Modules under this package MAY import ``azure-*`` SDKs. Everything under
``core/`` MUST talk to Azure only through the CSP-neutral Protocols in
``shared/providers/`` - these adapters are the only place a
provider-specific client is instantiated.
"""

from fdai.delivery.azure.programmatic_pipeline import (
    AzureIsolatedPipelineRunner,
    AzureIsolatedPipelineRunnerConfig,
    AzurePipelineSubmissionClient,
)

__all__ = [
    "AzureIsolatedPipelineRunner",
    "AzureIsolatedPipelineRunnerConfig",
    "AzurePipelineSubmissionClient",
]
