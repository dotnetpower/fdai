pub const ROLLED_BACK: &str = "rolled-back";
pub trait ReportProgress {
    fn attempt(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_terminal(mut report: String) -> bool {
    if report.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_no_effect_expiry(mut report: String) -> bool {
    if report.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_report_progress(mut previous: Option<String>, mut current: String) -> Result<(), &'static str> {
    if previous.is_none() {
        return Ok(());
    }
    if is_terminal((previous.clone()).unwrap_or_default()) {
        return Err("a terminal report cannot be followed by another report");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn failure_suppressions(mut plan: String, mut now: String, mut hold: String) -> Vec<String> {
    if plan.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

