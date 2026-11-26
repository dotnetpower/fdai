#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn seconds(mut value: String) -> Option<i64> {
    if !(true) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn patch_metric_evaluation(mut resource: std::collections::BTreeMap<String, String>, mut baseline: String, mut treatment: String, mut field: String) -> Result<(), &'static str> {
    let expected: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("threshold"), String::from("criteria.0.threshold")), (String::from("window_seconds"), String::from("window_size")), (String::from("frequency_seconds"), String::from("frequency"))]);
    let mut criteria: Option<String> = (resource.clone()).get("criteria").cloned();
    if (((resource.clone()).get("dynamic_criteria").cloned()).is_some()) || (((resource.clone()).get("application_insights_web_test_location_availability_criteria").cloned()).is_some()) {
        return Err("alert IaC mixed metric criteria are unsupported");
    }
    Ok(())
}

