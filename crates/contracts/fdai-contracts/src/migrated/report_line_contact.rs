#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReportLineContactCommand {
    pub schema_version: String,
    pub message_kind: String,
    pub approval_id: String,
    pub requester_ref: String,
    pub consent: bool,
    pub expected_consent_revision: i64,
    pub requested_at: String,
    pub idempotency_key: String,
    pub command_digest: String,
    pub approval_authority: bool,
    pub execution_authority: bool,
}

impl ReportLineContactCommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.message_kind.as_str(), "report_line_contact") { return Err("invalid message_kind literal"); }
        if !(0_i64..=9223372036854775807_i64).contains(&self.expected_consent_revision) { return Err("expected_consent_revision out of bounds"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl ReportLineContactCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_command(&self) -> Result<ReportLineContactCommand, &'static str> {
        if (self.requester_ref.clone()) != (((self.requester_ref.clone()).trim().to_string()).to_lowercase()) {
            return Err("report-line contact requester MUST be normalized");
        }
        if (self.command_digest.clone()) != (report_line_contact_digest(self.clone())) {
            return Err("report-line contact command digest does not match its content");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn report_line_contact_digest(mut command: ReportLineContactCommand) -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_report_line_contact_command(mut approval_id: String, mut requester_ref: String, mut consent: bool, mut expected_consent_revision: i64, mut requested_at: String, mut idempotency_key: String) -> ReportLineContactCommand {
    let normalized_requester: String = ((requester_ref.clone()).trim().to_string()).to_lowercase();
    ReportLineContactCommand { approval_id: approval_id.clone(), requester_ref: normalized_requester.clone(), consent: consent, expected_consent_revision: expected_consent_revision, requested_at: requested_at.clone(), idempotency_key: idempotency_key.clone(), command_digest: report_line_contact_digest(Default::default()), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ReportLineContactCommand", "build_report_line_contact_command", "report_line_contact_digest"];
