#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CatalogReadToolId {
    #[default]
    ResolveResource,
    GetResourceState,
    QueryResourceActivity,
    QueryResourceHealth,
    QueryGuestShutdownEvents,
    QueryNetworkSecurity,
    QueryNetworkPeerings,
    QueryArgTable,
    QueryMonitorLogTable,
    QueryPlatformMetrics,
    QueryAmbaAlerts,
    QueryCausalMechanism,
    QueryDiagnosticProbe,
    QueryAdvisorRecommendations,
    QueryPolicyCompliance,
    QuerySecurityAssessments,
    QueryUpdateAssessments,
    QueryServiceHealth,
    QueryResourceChanges,
    QueryTopologyRelationships,
}

impl CatalogReadToolId {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResolveResource => "resolve_resource",
            Self::GetResourceState => "get_resource_state",
            Self::QueryResourceActivity => "query_resource_activity",
            Self::QueryResourceHealth => "query_resource_health",
            Self::QueryGuestShutdownEvents => "query_guest_shutdown_events",
            Self::QueryNetworkSecurity => "query_network_security",
            Self::QueryNetworkPeerings => "query_network_peerings",
            Self::QueryArgTable => "query_arg_table",
            Self::QueryMonitorLogTable => "query_monitor_log_table",
            Self::QueryPlatformMetrics => "query_platform_metrics",
            Self::QueryAmbaAlerts => "query_amba_alerts",
            Self::QueryCausalMechanism => "query_causal_mechanism",
            Self::QueryDiagnosticProbe => "query_diagnostic_probe",
            Self::QueryAdvisorRecommendations => "query_advisor_recommendations",
            Self::QueryPolicyCompliance => "query_policy_compliance",
            Self::QuerySecurityAssessments => "query_security_assessments",
            Self::QueryUpdateAssessments => "query_update_assessments",
            Self::QueryServiceHealth => "query_service_health",
            Self::QueryResourceChanges => "query_resource_changes",
            Self::QueryTopologyRelationships => "query_topology_relationships",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CatalogReadToolSpec {
    pub tool_id: CatalogReadToolId,
    pub owner_agent: String,
    pub domain: String,
    pub timeout_seconds: i64,
    pub max_rows: i64,
    pub side_effect_class: String,
    pub execution_authority: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CatalogReadInvestigationDispatcher {
    pub initialized: bool,
}

impl CatalogReadInvestigationDispatcher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn coverage_summary(&self) -> std::collections::BTreeMap<String, i64> {
        std::collections::BTreeMap::from([(String::from("arg_tables"), 0_i64), (String::from("arg_resource_types"), 0_i64), (String::from("arm_schema_types"), 0_i64), (String::from("arg_relationship_mappings"), 0_i64), (String::from("monitor_log_categories"), 0_i64), (String::from("monitor_log_tables"), 0_i64), (String::from("canonical_resource_types"), 0_i64), (String::from("platform_metric_recipes"), 0_i64), (String::from("kql_telemetry_recipes"), 0_i64), (String::from("semantic_metric_definitions"), 0_i64), (String::from("amba_alert_recipes"), 0_i64), (String::from("causal_telemetry_mechanisms"), 0_i64), (String::from("diagnostic_probes"), 0_i64), (String::from("read_investigation_tools"), 0_i64)])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn compile_direct_query(&self, mut tool_id: CatalogReadToolId, mut subscription_ids: Vec<String>, mut target: String, mut limit: i64) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("tool_id"), String::new()), (String::from("owner"), String::new()), (String::from("domain"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CATALOG_READ_TOOL_SPECS", "CatalogReadInvestigationDispatcher", "CatalogReadToolId", "CatalogReadToolSpec"];
