import type { PillKind } from "../components/ui";
import type { FacetMap } from "./rule-catalog-components";
import type { DetailState as RuleDetailState } from "./rule-catalog-state";

export interface RuleDto {
  readonly id: string;
  readonly origin: string;
  readonly version: string;
  readonly source: string;
  readonly severity: string;
  readonly category: string;
  readonly resource_type: string;
  readonly check_logic: { readonly kind: string; readonly reference: string };
  readonly remediation: {
    readonly template_ref: string;
    readonly cost_impact_monthly_usd: number | null;
  };
  readonly remediates: string;
  readonly provenance: {
    readonly source_url: string;
    readonly license: string;
    readonly redistribution: string;
  };
}

export interface RuleCatalogResponse {
  readonly total: number;
  readonly filtered_total: number;
  readonly offset: number;
  readonly limit: number;
  readonly resource_type_count: number;
  readonly facets: {
    readonly by_origin: FacetMap;
    readonly by_category: FacetMap;
    readonly by_severity: FacetMap;
    readonly by_source: FacetMap;
  };
  readonly rules: readonly RuleDto[];
}

export interface RuleDetailDto extends RuleDto {
  readonly schema_version: string;
  readonly alternatives: readonly string[];
  readonly parameters: Readonly<Record<string, unknown>>;
  readonly applies_to: Readonly<Record<string, unknown>>;
  readonly check_logic_body: string | null;
  readonly remediation_body: string | null;
  readonly explanation: {
    readonly title: string | null;
    readonly description: string | null;
    readonly source: string | null;
    readonly details: Readonly<Record<string, unknown>>;
  };
  readonly provenance: {
    readonly source_url: string;
    readonly source_version: string | null;
    readonly resolved_ref: string;
    readonly content_hash: string;
    readonly license: string;
    readonly redistribution: string;
    readonly retrieved_at: string;
    readonly mapped_by: string | null;
  };
}

export interface FindingDto {
  readonly resource_id: string;
  readonly resource_name?: string | null;
  readonly severity?: string;
  readonly problem?: string;
  readonly context?: Readonly<Record<string, unknown>>;
  readonly observed_at?: string;
}

export interface FindingsResponse {
  readonly rule_id: string;
  readonly origin: string;
  readonly evaluated: boolean;
  readonly finding_count?: number;
  readonly findings: readonly FindingDto[];
}

export interface RuleActivationDeltaDto {
  readonly rule_id: string;
  readonly enabled: boolean;
}

export interface PendingRuleActivationRequest {
  readonly request_id: string;
  readonly proposal_digest: string;
  readonly expected_generation_digest: string;
  readonly requested_by: string;
  readonly requested_at: string;
  readonly reason: string;
  readonly changes: readonly RuleActivationDeltaDto[];
}

export interface RuleActivationStatusDto {
  readonly revision: number;
  readonly generation_id: string;
  readonly generation_digest: string;
  readonly profile_id: string;
  readonly profile_version: string;
  readonly active_rule_count: number;
  readonly active_rule_ids: readonly string[];
  readonly source: string;
  readonly source_ref: string;
  readonly requested_by: string;
  readonly approver_ids: readonly string[];
  readonly activated_at: string;
  readonly pending_requests: readonly PendingRuleActivationRequest[];
  readonly pending_truncated: boolean;
  readonly execution_authority: false;
}

export interface RuleActivationHistoryItem {
  readonly request_id: string;
  readonly status: "applied" | "already_applied" | "conflict" | "rejected" | "failed";
  readonly enabled: boolean;
  readonly source: string;
  readonly source_ref: string;
  readonly requested_by: string;
  readonly approver_ids: readonly string[];
  readonly reason: string;
  readonly previous_generation_digest: string | null;
  readonly resulting_generation_digest: string | null;
  readonly completed_at: string;
  readonly readback_verified: boolean;
  readonly failure_reason: string | null;
}

export interface RuleActivationHistoryDto {
  readonly rule_id: string;
  readonly history: readonly RuleActivationHistoryItem[];
  readonly truncated: boolean;
}

export type DetailState = RuleDetailState<RuleDetailDto>;

export type FindingsState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: FindingsResponse }
  | { readonly status: "error"; readonly message: string };

export type ActivationState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: RuleActivationStatusDto }
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string };

export type ActivationHistoryState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: RuleActivationHistoryDto }
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string };

export const SEVERITY_PILL: Readonly<Record<string, PillKind>> = {
  critical: "danger",
  high: "warning",
  medium: "info",
  low: "neutral",
};
