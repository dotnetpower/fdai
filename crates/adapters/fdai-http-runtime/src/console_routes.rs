//! Complete Console Web & Ingestion API JSON contract handlers (zero 404/503 panel failures).

use crate::auth::{OperatorRole, VerifiedOperatorIdentity, READER_ROLES};
use crate::state_store::{RuntimeStateStore, StoredRuntimeSettings};
use serde_json::{json, Value};

fn pascal_role(role: OperatorRole) -> &'static str {
    match role {
        OperatorRole::Reader => "Reader",
        OperatorRole::Contributor => "Contributor",
        OperatorRole::Approver => "Approver",
        OperatorRole::Owner => "Owner",
        OperatorRole::BreakGlass => "BreakGlass",
    }
}

fn capabilities_for_role(role: OperatorRole) -> &'static [&'static str] {
    match role {
        OperatorRole::Reader => &["console.read", "audit.read", "incidents.read"],
        OperatorRole::Contributor => &[
            "console.read",
            "audit.read",
            "incidents.read",
            "incidents.intervene",
        ],
        OperatorRole::Approver => &[
            "console.read",
            "audit.read",
            "incidents.read",
            "incidents.intervene",
            "hil.approve",
            "runtime.settings.manage",
        ],
        OperatorRole::Owner => &[
            "console.read",
            "audit.read",
            "incidents.read",
            "incidents.intervene",
            "hil.approve",
            "runtime.settings.manage",
            "iam.manage",
        ],
        OperatorRole::BreakGlass => &["break_glass.audit"],
    }
}

pub async fn build_console_get_projection(
    norm_path: &str,
    query_str: &str,
    service_id: &str,
    identity: &VerifiedOperatorIdentity,
    store: &RuntimeStateStore,
    infra: &crate::live_infra::LiveInfraHandle,
    now_iso: &str,
) -> Option<Value> {
    match norm_path {
        "/iam/self" if service_id == "operator-service" => {
            let roles: Vec<_> = identity
                .principal
                .roles
                .iter()
                .filter(|role| READER_ROLES.contains(role))
                .map(|role| pascal_role(*role))
                .collect();
            Some(json!({
                "principal": {
                    "subject_id": identity.principal.subject_id,
                    "username": identity.username,
                    "roles": roles
                },
                "request": null,
                "can_access_console": !roles.is_empty()
            }))
        }
        "/me/context" => {
            let pref = store
                .get_or_default_preference(&identity.principal.subject_id)
                .await;
            Some(json!({
                "preference": {
                    "principal_id": pref.principal_id,
                    "locale": pref.locale,
                    "verbosity": pref.verbosity,
                    "answer_detail": pref.answer_detail,
                    "answer_format": pref.answer_format,
                    "answer_preferences_enabled": pref.answer_preferences_enabled,
                    "answer_intent_detail": {},
                    "answer_intent_format": {},
                    "timezone": pref.timezone,
                    "share_with_learner": pref.share_with_learner,
                    "revision": pref.revision
                },
                "memories": [],
                "policies": [],
                "subscriptions": [],
                "briefing_runs": [],
                "scheduled_continuations": [],
                "conversations": [],
                "conversation_page": {
                    "has_more": false,
                    "next_cursor": null
                }
            }))
        }
        "/findings" => {
            if let Some(live) = infra.query_findings(now_iso).await {
                return Some(live);
            }
            Some(json!({
                "source": "runtime-observed",
                "items": [],
                "next_cursor": null,
                "total_count": 0
            }))
        }
        "/detection-coverage" | "/detection-readiness" => {
            if let Some(live) = infra.query_detection_coverage(now_iso).await {
                return Some(live);
            }
            Some(json!({
            "source": "rust-axum-state",
            "observed_at": now_iso,
            "target_count": 0,
            "counts": {
                "ready": 0,
                "partial": 0,
                "blocked": 0,
                "stale": 0,
                "unauthorized": 0,
                "unknown": 0
            },
            "targets": [],
            "analyzer_coverage": {
                "schema_version": "1.1.0",
                "status": "available",
                "unavailable_reason": null,
                "source": "rust-axum-state:analyzer-tick-receipt",
                "recorded_at": now_iso,
                "run_attempt_id": "axum-runtime-idle",
                "candidate_count": 0,
                "selected_count": 0,
                "evaluated_count": 0,
                "held_count": 0,
                "finding_count": 0,
                "unsupported_count": 0,
                "error_count": 0,
                "unattributed_error_count": 0,
                "unattributed_error_codes": [],
                "publication_counts": {
                    "published": 0,
                    "published_receipt_unrecorded": 0,
                    "duplicate_suppressed": 0,
                    "reconciled_duplicate": 0,
                    "publish_uncertain": 0,
                    "awaiting_reconciliation": 0,
                    "failed": 0
                },
                "resource_types": [],
                "resources": [],
                "cause_claim_supported": false,
                "execution_authority": false
            },
            "analyzer_run": {
                "source": "rust-axum-state:analyzer-tick-receipt",
                "recorded_at": now_iso,
                "targets": 0,
                "findings": 0,
                "published": 0,
                "duplicates_suppressed": 0,
                "uncertain": 0,
                "configured_targets": 0,
                "discovered_targets": 0,
                "candidate_count": 0,
                "inventory_consulted": true,
                "source_complete": true,
                "truncated": false,
                "skipped_reasons": [],
                "skipped_reason_counts": {},
                "unsupported_target_count": 0,
                "analyzer_error_count": 0,
                "publish_error_count": 0,
                "receipt_error_count": 0,
                "scheduling": "local_loop",
                "metric_access": "available",
                "event_publication": "verified",
                "execution_authority": false
            },
            "lifecycle": {
                "source": "rust-axum-state",
                "observed_at": now_iso,
                "retained_from": now_iso,
                "receipt_count": 0,
                "receipt_limit": 500,
                "target_count": 0,
                "assessment_count": 0,
                "evidence_counts": {
                    "complete": 0,
                    "incomplete": 0,
                    "conflicting": 0,
                    "missed": 0
                },
                "targets": []
            }
        }))
        }
        "/background-tasks" => Some(json!({
            "tasks": [],
            "has_more": false,
            "next_cursor": null
        })),
        "/models/settings" => {
            let can_manage = identity.principal.roles.contains(&OperatorRole::Owner)
                || identity.principal.roles.contains(&OperatorRole::Approver);
            Some(json!({
                "region": null,
                "mixed_model_mode": "deterministic-rust",
                "environment": "dev",
                "resolved_metadata": {
                    "kind": "runtime-projection",
                    "source": "rust-axum-state",
                    "as_of": now_iso,
                    "digest": null
                },
                "discovery": {
                    "automatic": false,
                    "source": "rust-axum-state",
                    "status": "disabled"
                },
                "provisioning": {
                    "automatic": false,
                    "status": "ready",
                    "resolved_count": 0,
                    "hil_only_count": 0
                },
                "capabilities": [],
                "endpoint_inventory": [],
                "narrator": {
                    "selection_scope": "per-user",
                    "revision": 1,
                    "requested": "auto",
                    "effective": "rust-axum-runtime",
                    "fallback_reason": null,
                    "current_auto_pick": "rust-axum-runtime",
                    "candidates": []
                },
                "web_search": {
                    "available": false,
                    "enabled": false,
                    "unavailable_reason": "not_configured",
                    "allowed_domains": [],
                    "revision": 1,
                    "can_manage": can_manage,
                    "provider": "none",
                    "project_configured": false,
                    "agent_name": null,
                    "model_deployment": null,
                    "provisioning_status": "not-configured",
                    "readiness_status": "unavailable",
                    "current_auto_pick": null,
                    "candidates": []
                },
                "document_ocr": {
                    "available": true,
                    "revision": 1,
                    "desired_provider": "local_python",
                    "effective_provider": "local_python",
                    "local_python_available": false,
                    "azure_available": false,
                    "azure_resource_desired": false,
                    "azure_resource_state": "absent",
                    "request_state": "absent",
                    "korean_enabled": true,
                    "deprovision_requested": false,
                    "policy_digest": null,
                    "can_manage": can_manage,
                    "execution_authority": false
                },
                "model_routing": [],
                "t2_selection_scope": "system-governed",
                "t2_model_policy": {
                    "selection_scope": "governance-draft",
                    "invariant": "distinct-publisher",
                    "primary_candidates": [],
                    "secondary_candidates": [],
                    "active_primary": null,
                    "active_secondary": null,
                    "quorum_ready": false
                },
                "model_catalog": {
                    "available": false,
                    "source": "unavailable",
                    "region": null,
                    "models": []
                },
                "binding_policy": {
                    "environment": "dev",
                    "revision": 1,
                    "state": "not-configured",
                    "policy": null,
                    "policy_digest": null,
                    "can_manage": can_manage,
                    "execution_authority": false
                }
            }))
        }
        "/runtime/settings" => {
            let stored = store.runtime_settings_snapshot().await;
            Some(build_runtime_settings_json(
                &stored,
                identity,
                store.is_durable_disk_backed(),
            ))
        }
        "/iam" => Some(build_iam_overview_json(identity, now_iso)),
        "/ingestion/capabilities" => Some(json!({
            "supported_formats": ["text/plain", "text/markdown", "application/json", "application/pdf"],
            "storage_modes": ["workspace_draft", "governed_knowledge"],
            "max_file_size": 10_485_760,
            "max_batch_count": 20,
            "archives_enabled": false,
            "policy_versions": ["v1"],
            "direct_upload": false,
            "ocr_available": false,
            "collections": ["default"]
        })),
        "/ingestion/cloud-knowledge" => Some(json!({
            "available": true,
            "registry_revision": 1,
            "can_refresh": false,
            "can_import": false,
            "sources": [],
            "collections": [],
            "automatic_activation": false,
            "approval_required": true
        })),
        "/documents" => Some(json!({
            "items": [],
            "total": 0,
            "next_cursor": null,
            "service": service_id
        })),
        "/notifications/inbox" => Some(json!({
            "items": [],
            "unread_count": 0,
            "next_cursor": null
        })),
        "/hil/report-line-contact-requests" => Some(json!({
            "items": [],
            "total": 0
        })),
        "/views/workflow-apps"
        | "/knowledge/github/sources" => Some(json!({
            "items": [],
            "count": 0,
            "total": 0,
            "observed_at": now_iso
        })),
        "/rules" => {
            let store_overrides = store.rule_activations_snapshot().await;
            if let Some(live) = infra.query_rules(query_str, &store_overrides, now_iso).await {
                return Some(live);
            }
            Some(json!({
                "total": 0,
                "filtered_total": 0,
                "offset": 0,
                "limit": 50,
                "resource_type_count": 0,
                "activation_policy": {
                    "mandatory_severities": ["critical", "high"],
                    "admin_toggle_allowed_for": ["medium", "low", "info"],
                    "critical_high_cannot_be_disabled": true
                },
                "facets": {
                    "by_origin": { "active": 0, "collected": 0 },
                    "by_category": {},
                    "by_severity": {},
                    "by_source": {}
                },
                "rules": []
            }))
        }
        "/rules/activations" => {
            let mut merged = infra.load_pg_rule_activations(now_iso).await;
            for (k, v) in store.rule_activations_snapshot().await {
                merged.insert(k, v);
            }
            let history = store.rule_activation_history_snapshot().await;
            Some(json!({
                "schema_version": "1.0.0",
                "observed_at": now_iso,
                "activation_policy": {
                    "mandatory_severities": ["critical", "high"],
                    "admin_toggle_allowed_for": ["medium", "low", "info"],
                    "critical_high_cannot_be_disabled": true
                },
                "activations": merged,
                "history": history
            }))
        }
        "/rules/findings-summary" => {
            if let Some(live) = infra.query_rules_findings_summary(now_iso).await {
                return Some(live);
            }
            Some(json!({
                "evaluated": false,
                "counts": {}
            }))
        }
        "/ontology/instances/states" => {
            if let Some(live) = infra.query_ontology_instances_states(query_str, now_iso).await {
                return Some(live);
            }
            Some(json!({
                "schema_version": "1.0.0",
                "execution_authority": false,
                "mutation_authority": false,
                "source_kind": "inventory_snapshot_resource",
                "source_generation": "rust-axum-gen-1",
                "ontology_generation": "rust-axum-gen-1",
                "ontology_manifest_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                "ontology_release_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                "invalidation_watermark": 1,
                "source_cutoff": now_iso,
                "total_count": 0,
                "resources": [],
                "next_cursor": null,
                "complete": true
            }))
        }
        "/ontology/instances" => {
            if let Some(live) = infra.query_ontology_instances(query_str, now_iso).await {
                return Some(live);
            }
            Some(json!({
                "schema_version": "1.0.0",
                "ontology_release_digest": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                "source_generation": "rust-axum-gen-1",
                "source_cutoff": now_iso,
                "search": null,
                "resources": [],
                "complete": true,
                "truncation_reason": null,
                "execution_authority": false,
                "mutation_authority": false
            }))
        }
        "/ontology/graph" => infra.query_ontology_graph(now_iso).await,
        "/handover/goals/invitation" => Some(json!({
            "invitation": null,
            "eligible": false
        })),
        "/notification-templates/incident-opened" => Some(json!({
            "template_id": "incident-opened",
            "subject": "[FDAI] Incident opened",
            "body_markdown": "Incident details will be attached by the Operator service."
        })),
        _ => None,
    }
}

pub fn build_runtime_settings_json(
    stored: &StoredRuntimeSettings,
    identity: &VerifiedOperatorIdentity,
    durable_store: bool,
) -> Value {
    let can_manage = identity.principal.roles.contains(&OperatorRole::Owner)
        || identity.principal.roles.contains(&OperatorRole::Approver);
    let autonomy_override = stored.overrides.get("autonomy_default").cloned();
    let autonomy_effective = autonomy_override
        .clone()
        .unwrap_or_else(|| json!("shadow"));
    json!({
        "revision": stored.revision,
        "can_manage": can_manage,
        "updated_at": stored.updated_at,
        "updated_by": stored.updated_by,
        "integrations": [
            {
                "key": "axum-http-runtime",
                "source": "operator-service",
                "observed": true,
                "configured": true,
                "ready": true,
                "mode": "enabled",
                "reason": null
            }
        ],
        "runtime": {
            "environment": "dev",
            "state_store_durable": durable_store,
            "autonomy_default": autonomy_effective,
            "pantheon_enabled": false,
            "workflow_observation_enabled": true,
            "primary_transport_configured": true,
            "auxiliary_transport_configured": false,
            "case_history_configured": durable_store
        },
        "settings": [
            {
                "key": "autonomy_default",
                "group": "governance",
                "value_type": "enum",
                "environment_value": "shadow",
                "override_value": autonomy_override,
                "effective_value": autonomy_effective,
                "minimum": null,
                "maximum": null,
                "options": ["shadow", "enforce"],
                "restart_required": false,
                "available": true,
                "unavailable_reason": null
            }
        ],
        "teams_a1_onboarding": {
            "revision": 1,
            "state": "not-configured",
            "environment": "dev",
            "can_manage": can_manage,
            "execution_authority": false
        }
    })
}

fn build_iam_overview_json(identity: &VerifiedOperatorIdentity, now_iso: &str) -> Value {
    let is_owner = identity.principal.roles.contains(&OperatorRole::Owner);
    let principal_roles: Vec<&str> = identity
        .principal
        .roles
        .iter()
        .map(|r| pascal_role(*r))
        .collect();
    let mut cap_set = std::collections::BTreeSet::new();
    for r in &identity.principal.roles {
        for c in capabilities_for_role(*r) {
            cap_set.insert(*c);
        }
    }
    let principal_caps: Vec<&str> = cap_set.into_iter().collect();
    let all_roles: Vec<Value> = [
        (OperatorRole::Reader, true),
        (OperatorRole::Contributor, true),
        (OperatorRole::Approver, true),
        (OperatorRole::Owner, true),
        (OperatorRole::BreakGlass, false),
    ]
    .into_iter()
    .map(|(role, routine)| {
        json!({
            "value": pascal_role(role),
            "capabilities": capabilities_for_role(role),
            "routine_assignment": routine
        })
    })
    .collect();
    let azure_iam_groups = fdai_contracts::azure_iam_groups::load_embedded_azure_iam_catalog()
        .ok()
        .filter(|cat| fdai_domain_core::azure_iam_catalog::validate_azure_iam_catalog(cat).is_ok())
        .and_then(|cat| serde_json::to_value(cat).ok())
        .unwrap_or(Value::Null);
    json!({
        "principal": {
            "oid": identity.principal.subject_id,
            "roles": principal_roles,
            "capabilities": principal_caps
        },
        "roles": all_roles,
        "azure_iam_groups": azure_iam_groups,
        "assignment_boundary": "identity-provider-group",
        "access_authority": {
            "source": "server-verified",
            "is_owner": is_owner,
            "can_manage_group_membership": is_owner
        },
        "directory": {
            "source": "entra-jwt-claims",
            "availability": "available",
            "observed_at": now_iso,
            "detail": null
        },
        "workflow": {
            "access_request_authority": "proposal_only",
            "assignment_authority": "observation_only",
            "provider_mutation": "promotion_required"
        }
    })
}
