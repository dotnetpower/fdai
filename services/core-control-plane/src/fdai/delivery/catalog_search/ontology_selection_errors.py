"""Content-free failures at the existing typed-selection verification boundaries."""

from enum import StrEnum


class SelectionFailure(StrEnum):
    REQUEST_INVALID = "request_invalid"
    SOURCE_UNAVAILABLE = "source_unavailable"
    SOURCE_SCOPE_CHANGED = "source_scope_changed"
    SOURCE_DRIFT = "source_drift"
    TIME_DRIFT = "time_drift"
    REGISTRY_UNAVAILABLE = "registry_unavailable"
    MODEL_BINDING_CHANGED = "model_binding_changed"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    PROPOSAL_UNAVAILABLE = "proposal_unavailable"
    PROPOSAL_TIMEOUT = "proposal_timeout"
    READ_TIMEOUT = "read_timeout"
    MEMBERSHIP_TIMEOUT = "membership_timeout"
    FUNCTION_TIMEOUT = "function_timeout"
    PROPOSAL_CONTRACT_INVALID = "proposal_contract_invalid"
    PROPOSAL_BINDING_CHANGED = "proposal_binding_changed"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    UNSUPPORTED_CONSTRAINT = "unsupported_constraint"
    AMBIGUOUS_REQUEST = "ambiguous_request"
    CITATION_INVALID = "citation_invalid"
    SELECTION_BOUND = "selection_bound"
    SELECTION_BINDING_CHANGED = "selection_binding_changed"
    MEMBERSHIP_INCOMPLETE = "membership_incomplete"
    MEMBERSHIP_DENIED = "membership_denied"
    PREDICATE_INVALID = "predicate_or_membership_invalid"
    AGREEMENT_MISMATCH = "agreement_mismatch"
    EVIDENCE_INVALID = "evidence_invalid"
    FUNCTION_CONTRACT_INVALID = "function_contract_invalid"


class CandidateSelectionError(ValueError):
    def __init__(self, reason: SelectionFailure) -> None:
        self.reason = SelectionFailure(reason)
        message = {
            SelectionFailure.SELECTION_BOUND: (
                "ontology candidate selection exceeds its input bound"
            ),
            SelectionFailure.SELECTION_BINDING_CHANGED: (
                "ontology candidate selection binding or ObjectType mismatch"
            ),
            SelectionFailure.MEMBERSHIP_INCOMPLETE: (
                "ontology candidate selection requires complete current evidence"
            ),
            SelectionFailure.SOURCE_DRIFT: "ontology candidate selection source content changed",
        }.get(self.reason, "typed selection membership failed")
        super().__init__(f"{message} [{self.reason}]")


class CandidateSelectionDeniedError(PermissionError):
    reason = SelectionFailure.MEMBERSHIP_DENIED

    def __init__(self) -> None:
        super().__init__("object-set predicate property is not readable [membership_denied]")


class GovernedReadError(PermissionError):
    def __init__(self, reason: SelectionFailure) -> None:
        self.reason = SelectionFailure(reason)
        message = {
            SelectionFailure.REQUEST_INVALID: "typed selection read arguments are invalid",
            SelectionFailure.PROPOSAL_UNAVAILABLE: (
                "typed selection qualified proposer is unavailable"
            ),
            SelectionFailure.SOURCE_UNAVAILABLE: (
                "typed selection requires the current authenticated read source"
            ),
            SelectionFailure.SOURCE_SCOPE_CHANGED: "typed selection current source scope changed",
            SelectionFailure.AGREEMENT_MISMATCH: "typed selection proposals disagree",
        }.get(self.reason, "typed selection read held")
        super().__init__(f"{message} [{self.reason}]")

    @property
    def clarification(self) -> bool:
        return self.reason in {
            SelectionFailure.UNRESOLVED_REFERENCE,
            SelectionFailure.UNSUPPORTED_CONSTRAINT,
            SelectionFailure.AMBIGUOUS_REQUEST,
        }
