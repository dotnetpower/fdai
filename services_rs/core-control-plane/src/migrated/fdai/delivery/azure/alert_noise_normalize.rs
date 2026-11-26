pub const GUID: &str = "[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn canonical_json(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: String) -> Result<String, &'static str> {
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object_value(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let result: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("provider object is malformed");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn list_value(mut value: String, mut maximum: i64) -> Result<Vec<String>, &'static str> {
    if (!(false)) || ((((value.clone()).len() as i64)) > (maximum)) {
        return Err("provider array is malformed or exceeds its bound");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn native_scope(mut value: String) -> Result<String, &'static str> {
    let result: String = text(value.clone()).unwrap_or_else(|_| String::new());
    Ok((result.clone()).to_lowercase())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn within_scope(mut resource: String, mut scope: String) -> bool {
    if resource.is_empty() {
        return false;
    }
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn native_resource(mut raw: std::collections::BTreeMap<String, String>, mut expected_type: String) -> Result<String, &'static str> {
    let resource: String = native_scope(String::new()).unwrap_or_else(|_| String::new());
    let parts: Vec<String> = (resource.clone()).split("/").map(str::to_string).collect::<Vec<String>>();
    Ok(resource.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn group_id(mut value: String) -> Result<String, &'static str> {
    let resource: String = native_scope(value.clone()).unwrap_or_else(|_| String::new());
    let parts: Vec<String> = (resource.clone()).split("/").map(str::to_string).collect::<Vec<String>>();
    Ok(resource.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn rule_groups(mut properties: std::collections::BTreeMap<String, String>, mut kind: String) -> Result<Vec<String>, &'static str> {
    if ((kind.clone()) == (String::from("activity"))) && (!((properties.clone()).contains_key("actions"))) {
        return Err("activity alert actions are missing");
    }
    if (kind.clone()) == (String::from("metric")) {
        let mut rows: Vec<String> = list_value(String::new(), 5_i64).unwrap_or_else(|_| Vec::new());
    } else {
        let mut rows: Vec<String> = list_value(String::new(), 5_i64).unwrap_or_else(|_| Vec::new());
    }
    let mut result: Vec<String> = Vec::<String>::new();
    if ((((result.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((result.clone()).len() as i64)) {
        return Err("provider rule action is duplicated");
    }
    Ok({ let mut _v = result.clone(); _v.sort(); _v })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn notification_kind(mut key: String, mut receiver: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if (receiver.clone()).contains_key("status") {
        let _ = text(String::new()).unwrap_or_else(|_| String::new());
    }
    if (key.clone()) == (String::from("armRoleReceivers")) {
        return Ok(String::from("role"));
    }
    Ok(String::from("direct"))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn metric_evaluation(mut properties: std::collections::BTreeMap<String, String>, mut opaque: String) -> Option<String> {
    let criteria: std::collections::BTreeMap<String, String> = object_value(properties.clone(), String::from("criteria")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let rows: Vec<String> = list_value(String::new(), 0_i64).unwrap_or_else(|_| Vec::new());
    let known: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("criterionType"), String::from("name"), String::from("metricName"), String::from("metricNamespace"), String::from("operator"), String::from("timeAggregation"), String::from("threshold"), String::from("dimensions"), String::from("skipMetricValidation")]);
    let _ = text(String::new()).unwrap_or_else(|_| String::new());
    let metric: String = text(String::new()).unwrap_or_else(|_| String::new());
    let window: i64 = duration_seconds(String::new()).unwrap_or_else(|_| 0_i64);
    let frequency: i64 = duration_seconds(String::new()).unwrap_or_else(|_| 0_i64);
    if (frequency) > (window) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn duration_seconds(mut raw: String) -> Result<i64, &'static str> {
    let values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("PT1M"), String::new()), (String::from("PT5M"), String::new()), (String::from("PT15M"), String::new()), (String::from("PT30M"), String::new()), (String::from("PT1H"), String::new()), (String::from("PT6H"), String::new()), (String::from("PT12H"), String::new()), (String::from("P1D"), String::new())]);
    if (!(true)) || (!((values.clone()).contains_key(raw.as_str()))) {
        return Err("unsupported metric duration");
    }
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn alert_rule(mut raw: std::collections::BTreeMap<String, String>, mut native: String, mut kind: String, mut bindings: Vec<String>, mut opaque: String, mut revision: String, mut authorized_scope: String, mut reasons: std::collections::BTreeSet<String>) -> Result<(String, Vec<String>), &'static str> {
    let properties: std::collections::BTreeMap<String, String> = object_value(raw.clone(), String::from("properties")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let scope_values: Vec<String> = list_value(String::new(), 0_i64).unwrap_or_else(|_| Vec::new());
    let _ = object_value(properties.clone(), if (kind.clone()) == (String::from("activity")) { String::from("condition") } else { String::from("criteria") }).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let evaluation: Option<String> = if (kind.clone()) == (String::from("metric")) { metric_evaluation(properties.clone(), opaque.clone()) } else { None };
    if ((kind.clone()) != (String::from("activity"))) && (evaluation.is_none()) {
        reasons.insert(String::from("evaluation_semantics_unavailable"));
    }
    Ok((String::new(), Vec::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
#[allow(clippy::too_many_arguments)]
pub fn processing_rule(mut raw: std::collections::BTreeMap<String, String>, mut native_rules: std::collections::BTreeMap<String, String>, mut opaque: String, mut revision: String, mut now: String, mut native_targets: Option<std::collections::BTreeMap<String, Vec<String>>>, mut native_groups: Option<std::collections::BTreeMap<String, String>>, mut authorized_scope: Option<String>) -> Result<Option<String>, &'static str> {
    let native: String = native_resource(raw.clone(), String::from("Microsoft.AlertsManagement/actionRules")).unwrap_or_else(|_| String::new());
    let properties: std::collections::BTreeMap<String, String> = object_value(raw.clone(), String::from("properties")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let actions: Vec<String> = list_value(String::new(), 5_i64).unwrap_or_else(|_| Vec::new());
    if (((actions.clone()).len() as i64)) != (1_i64) {
        return Ok(None);
    }
    let action_type: String = text(String::new()).unwrap_or_else(|_| String::new());
    let mut complete: bool = true;
    if (action_type.clone()) == (String::from("RemoveAllActionGroups")) {
        let mut action: String = String::from("suppress");
    } else if (action_type.clone()) == (String::from("AddActionGroups")) {
        let mut action: String = String::from("add");
    } else {
        return Ok(None);
    }
    let schedule: Option<String> = (properties.clone()).get("schedule").cloned();
    let Some(mut schedule) = schedule.clone() else { return Ok(None); };
    if !(false) {
        return Err("processing schedule is malformed");
    }
    if (text(String::new()).unwrap_or_else(|_| String::new())) != (String::from("UTC")) {
        return Ok(None);
    }
    if (!((schedule.clone()).contains("effectiveFrom"))) || (!((schedule.clone()).contains("effectiveUntil"))) {
        return Ok(None);
    }
    let recurrences: Vec<String> = list_value(String::new(), 0_i64).unwrap_or_else(|_| Vec::new());
    for recurrence in recurrences.clone() {
        if !(false) {
            return Err("processing recurrence is malformed");
        }
        let _ = text(String::new()).unwrap_or_else(|_| String::new());
    }
    let conditions: Vec<String> = list_value(String::new(), 0_i64).unwrap_or_else(|_| Vec::new());
    for condition in conditions.clone() {
        if !(false) {
            return Err("processing condition is malformed");
        }
        let _ = text(String::new()).unwrap_or_else(|_| String::new());
        let _ = text(String::new()).unwrap_or_else(|_| String::new());
        for value in list_value(String::new(), 5_i64).unwrap_or_else(|_| Vec::new()) {
            let _ = text(value.clone()).unwrap_or_else(|_| String::new());
        }
    }
    if authorized_scope.is_none() {
        complete = false;
    } else {
        let bound_scope: String = native_scope((authorized_scope.clone()).unwrap_or_default()).unwrap_or_else(|_| String::new());
    }
    let mut selected: Vec<String> = Vec::<String>::new();
    Ok(None)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn utc_time(mut value: String) -> Result<String, &'static str> {
    let raw: String = text(value.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

