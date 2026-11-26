#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum NotificationClaimStatus {
    #[default]
    Claimed,
    InProgress,
    Sent,
}

impl NotificationClaimStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Claimed => "claimed",
            Self::InProgress => "in_progress",
            Self::Sent => "sent",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct NotificationDeliveryClaim {
    pub status: NotificationClaimStatus,
    pub token: Option<String>,
}

pub trait IncidentNotificationDeliveryStore {
    fn claim(&self, audit_id: String, now: String, lease_seconds: i64) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryIncidentNotificationDeliveryStore {
    pub initialized: bool,
}

impl InMemoryIncidentNotificationDeliveryStore {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn claim(&self, mut audit_id: String, mut now: String, mut lease_seconds: i64) -> NotificationDeliveryClaim {
        let _ = validate_claim_input(audit_id.clone(), now.clone(), lease_seconds).unwrap_or_else(|_| ());
        NotificationDeliveryClaim::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn complete(&self, mut audit_id: String, mut token: String, mut at: String) -> Result<(), &'static str> {
        if ((token.clone()).trim().to_string()).is_empty() {
            return Err("incident notification claim token MUST be non-empty");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn release(&self, mut audit_id: String, mut token: String) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_claim_input(mut audit_id: String, mut now: String, mut lease_seconds: i64) -> Result<(), &'static str> {
    if (audit_id.trim().to_string()).is_empty() {
        return Err("incident notification audit_id MUST be non-empty");
    }
    if (false) || ((lease_seconds) < (1_i64)) {
        return Err("incident notification lease_seconds MUST be  1");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["IncidentNotificationDeliveryStore", "InMemoryIncidentNotificationDeliveryStore", "NotificationClaimStatus", "NotificationDeliveryClaim"];
