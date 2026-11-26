pub const MAX_FRESHNESS_SECONDS: i64 = 31536000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PostgresRoleProjectionReason {
    #[default]
    Projected,
    WrongScope,
    Stale,
}

impl PostgresRoleProjectionReason {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Projected => "projected",
            Self::WrongScope => "wrong_scope",
            Self::Stale => "stale",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresRoleObservation {
    pub observation_id: String,
    pub role_name: String,
    pub service_ref: String,
    pub scope_ref: String,
    pub can_login: bool,
    pub superuser: bool,
    pub create_database: bool,
    pub create_role: bool,
    pub inherit: bool,
    pub replication: bool,
    pub bypass_row_level_security: bool,
    pub observed_at: String,
    pub evidence_cutoff: String,
    pub recorded_at: String,
    pub freshness_ceiling_seconds: i64,
    pub source_identity: String,
    pub source_revision: String,
    pub evidence_ref: String,
    pub authentication_ref: String,
    pub execution_authority: bool,
    pub mutation_authority: bool,
}

impl PostgresRoleObservation {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.observation_id.trim().is_empty() { return Err("observation_id must be non-empty"); }
        if self.role_name.trim().is_empty() { return Err("role_name must be non-empty"); }
        if self.service_ref.trim().is_empty() { return Err("service_ref must be non-empty"); }
        if self.scope_ref.trim().is_empty() { return Err("scope_ref must be non-empty"); }
        if self.observed_at.trim().is_empty() { return Err("observed_at must be non-empty"); }
        if self.evidence_cutoff.trim().is_empty() { return Err("evidence_cutoff must be non-empty"); }
        if self.recorded_at.trim().is_empty() { return Err("recorded_at must be non-empty"); }
        if self.source_identity.trim().is_empty() { return Err("source_identity must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        if self.evidence_ref.trim().is_empty() { return Err("evidence_ref must be non-empty"); }
        if self.authentication_ref.trim().is_empty() { return Err("authentication_ref must be non-empty"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.mutation_authority { return Err("mutation_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresRoleEvidence {
    pub service_ref: String,
    pub principal_handle: String,
    pub can_login: bool,
    pub superuser: bool,
    pub create_database: bool,
    pub create_role: bool,
    pub inherit: bool,
    pub replication: bool,
    pub bypass_row_level_security: bool,
    pub observed_at: String,
    pub evidence_cutoff: String,
    pub recorded_at: String,
    pub freshness_ceiling_seconds: i64,
    pub source_identity: String,
    pub source_revision: String,
    pub evidence_refs: Vec<String>,
    pub execution_authority: bool,
    pub mutation_authority: bool,
}

impl PostgresRoleEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.mutation_authority { return Err("mutation_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresRoleProjection {
    pub reason: PostgresRoleProjectionReason,
    #[allow(clippy::type_complexity)]
    pub evidence: Option<Box<PostgresRoleEvidence>>,
    pub digest: String,
    pub execution_authority: bool,
    pub mutation_authority: bool,
}

impl PostgresRoleProjection {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.mutation_authority { return Err("mutation_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn project_postgres_role_evidence(mut observation: PostgresRoleObservation, mut principal_scope_ref: String, mut readable_service_refs: Vec<String>, mut evaluation_time: String) -> Result<PostgresRoleProjection, &'static str> {
    if ((principal_scope_ref.trim().to_string()).is_empty()) || ((((principal_scope_ref.clone()).len() as i64)) > (512_i64)) {
        return Err("PostgreSQL role principal_scope_ref MUST be bounded non-empty text");
    }
    if (evaluation_time.clone()) < (observation.recorded_at.clone()) {
        return Err("PostgreSQL role evaluation_time MUST NOT precede recorded_at");
    }
    let readable: std::collections::BTreeSet<String> = (readable_service_refs.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
    let context: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("evaluation_time"), timestamp(evaluation_time.clone())), (String::from("principal_scope_ref"), principal_scope_ref.clone()), (String::from("readable_services_digest"), digest(String::new()))]);
    if ((observation.scope_ref.clone()) != (principal_scope_ref.clone())) || (!((readable.clone()).contains((observation.service_ref.clone()).as_str()))) {
        return Ok(projection(observation.clone(), Default::default(), context.clone(), None));
    }
    let evidence: PostgresRoleEvidence = PostgresRoleEvidence { service_ref: observation.service_ref.clone(), principal_handle: digest(String::new()), can_login: observation.can_login, superuser: observation.superuser, create_database: observation.create_database, create_role: observation.create_role, inherit: observation.inherit, replication: observation.replication, bypass_row_level_security: observation.bypass_row_level_security, observed_at: observation.observed_at.clone(), evidence_cutoff: observation.evidence_cutoff.clone(), recorded_at: observation.recorded_at.clone(), freshness_ceiling_seconds: observation.freshness_ceiling_seconds, source_identity: observation.source_identity.clone(), source_revision: observation.source_revision.clone(), ..Default::default() };
    Ok(projection(observation.clone(), Default::default(), context.clone(), Some(evidence.clone())))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn projection(mut observation: PostgresRoleObservation, mut reason: PostgresRoleProjectionReason, mut context: std::collections::BTreeMap<String, String>, mut evidence: Option<PostgresRoleEvidence>) -> PostgresRoleProjection {
    let body: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("context"), String::new()), (String::from("observation_digest"), digest(String::new())), (String::from("projected_evidence"), String::new()), (String::from("reason"), String::new())]);
    PostgresRoleProjection { reason: reason.clone(), evidence: (evidence.clone()).map(Box::new), digest: digest(String::new()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn observation_body(mut observation: PostgresRoleObservation) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("authentication_ref"), observation.authentication_ref.clone()), (String::from("bypass_row_level_security"), String::new()), (String::from("can_login"), String::new()), (String::from("create_database"), String::new()), (String::from("create_role"), String::new()), (String::from("evidence_cutoff"), timestamp(observation.evidence_cutoff.clone())), (String::from("evidence_ref"), observation.evidence_ref.clone()), (String::from("freshness_ceiling_seconds"), String::new()), (String::from("inherit"), String::new()), (String::from("observation_id"), observation.observation_id.clone()), (String::from("observed_at"), timestamp(observation.observed_at.clone())), (String::from("recorded_at"), timestamp(observation.recorded_at.clone())), (String::from("replication"), String::new()), (String::from("role_name"), observation.role_name.clone()), (String::from("scope_ref"), observation.scope_ref.clone()), (String::from("service_ref"), observation.service_ref.clone()), (String::from("source_identity"), observation.source_identity.clone()), (String::from("source_revision"), observation.source_revision.clone()), (String::from("superuser"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn evidence_body(mut evidence: Option<PostgresRoleEvidence>) -> Option<std::collections::BTreeMap<String, String>> {
    let Some(mut evidence) = evidence.clone() else { return None; };
    Some(std::collections::BTreeMap::from([(String::from("bypass_row_level_security"), String::new()), (String::from("can_login"), String::new()), (String::from("create_database"), String::new()), (String::from("create_role"), String::new()), (String::from("evidence_cutoff"), timestamp(evidence.evidence_cutoff.clone())), (String::from("evidence_refs"), String::new()), (String::from("freshness_ceiling_seconds"), String::new()), (String::from("inherit"), String::new()), (String::from("observed_at"), timestamp(evidence.observed_at.clone())), (String::from("principal_handle"), evidence.principal_handle.clone()), (String::from("recorded_at"), timestamp(evidence.recorded_at.clone())), (String::from("replication"), String::new()), (String::from("service_ref"), evidence.service_ref.clone()), (String::from("source_identity"), evidence.source_identity.clone()), (String::from("source_revision"), evidence.source_revision.clone()), (String::from("superuser"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn digest(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_digest(mut value: String) -> bool {
    if (!((value.clone()).starts_with("sha256:"))) || ((((value.clone()).len() as i64)) != (71_i64)) {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn timestamp(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresRoleEvidence", "PostgresRoleObservation", "PostgresRoleProjection", "PostgresRoleProjectionReason", "project_postgres_role_evidence"];
