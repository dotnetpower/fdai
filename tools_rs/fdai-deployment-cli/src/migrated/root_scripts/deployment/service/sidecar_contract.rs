#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SidecarContractError {
    pub message: String,
}

impl SidecarContractError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for SidecarContractError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for SidecarContractError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn planned_observable_configuration(mut container: std::collections::BTreeMap<String, String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if ((container.clone()).get("name").cloned()) != Some(name.clone()) {
        return Err("sidecar name name changed");
    }
    let cpu: Option<String> = (container.clone()).get("cpu").cloned();
    let memory: Option<String> = (container.clone()).get("memory").cloned();
    if (!(true)) || ((true) || (!(true))) {
        return Err("sidecar name resources are invalid");
    }
    Ok(std::collections::BTreeMap::from([(String::from("name"), name.clone()), (String::from("resources"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn observed_configuration(mut container: std::collections::BTreeMap<String, String>, mut name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let allowed: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("name"), String::from("image"), String::from("probes"), String::from("resources")]);
    if ((container.clone()).get("name").cloned()) != Some(name.clone()) {
        return Err("sidecar name name changed");
    }
    let resources: Option<String> = (container.clone()).get("resources").cloned();
    Ok(std::collections::BTreeMap::from([(String::from("name"), name.clone()), (String::from("resources"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn planned_observable_probes(mut probes: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, mut name: String) -> Result<std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, &'static str> {
    let mut normalized: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    for (probe_name, probe) in probes.clone() {
        let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        for (field, value) in probe.clone() {
            if (field.clone()) == (String::from("header")) {
                return Err("sidecar name probe_name headers are unsupported");
            }
            result.insert(field.clone(), value.clone());
        }
        normalized.insert(probe_name.clone(), result.clone());
    }
    Ok(normalized.clone())
}

