use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostApplicationReceipts {
    pub inventory: BTreeMap<String, String>,
    pub catalog_review: BTreeMap<String, String>,
    #[allow(clippy::type_complexity)]
    pub trial_activation: Option<BTreeMap<String, String>>,
}

impl PostApplicationReceipts {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn trial_open(&self) -> bool {
        let trial: Option<BTreeMap<String, String>> = self.trial_activation.clone();
        false
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn run_post_application_checkpoints(mut tunnel: String, mut remote_root: String, mut app_work: String, mut runtime_platform: String, mut remote_json: String) -> PostApplicationReceipts {
    let mut trial_activation: Option<String> = None;
    let _ = require_catalog_review_receipt(std::collections::BTreeMap::new()).unwrap_or_else(|_| ());
    PostApplicationReceipts::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_catalog_review_receipt(mut value: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
    let supplied_digest: Option<String> = (value.clone()).get("receipt_digest").cloned();
    if ((value.clone()).get("state").cloned()) == Some(String::from("skipped")) {
        return Ok(());
    }
    let required_labels: Option<String> = (value.clone()).get("required_labels").cloned();
    let observed_labels: Option<String> = (value.clone()).get("observed_labels").cloned();
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostApplicationReceipts", "require_catalog_review_receipt", "run_post_application_checkpoints"];
