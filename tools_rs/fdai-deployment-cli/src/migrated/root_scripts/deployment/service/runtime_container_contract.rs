#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RuntimeContainerContractError {
    pub message: String,
}

impl RuntimeContainerContractError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RuntimeContainerContractError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RuntimeContainerContractError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn planned_primary_configuration(mut container: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    let mut configuration: std::collections::BTreeMap<String, String> = common_configuration(container.clone(), false).unwrap_or_else(|_| std::collections::BTreeMap::new());
    configuration.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn observed_primary_configuration(mut container: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let allowed: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("args"), String::from("command"), String::from("env"), String::from("image"), String::from("name"), String::from("probes"), String::from("resources"), String::from("volumeMounts")]);
    let mut configuration: std::collections::BTreeMap<String, String> = common_configuration(container.clone(), true).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(configuration.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn configuration_digest(mut configuration: std::collections::BTreeMap<String, String>) -> String {
    if configuration.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn has_readiness_probe(mut configuration: std::collections::BTreeMap<String, String>) -> bool {
    let probes: Option<String> = (configuration.clone()).get("probes").cloned();
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn common_configuration(mut container: std::collections::BTreeMap<String, String>, mut observed: bool) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let name: Option<String> = (container.clone()).get("name").cloned();
    if (!(true)) || (!((name.clone()).is_some())) {
        return Err("primary container name is invalid");
    }
    let mut configuration: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("name"), (name.clone()).unwrap_or_default()), (String::from("command"), String::new()), (String::from("args"), String::new()), (String::from("env"), String::new())]);
    let resources: Option<std::collections::BTreeMap<String, String>> = resources(container.clone(), observed).unwrap_or_else(|_| None);
    Ok(configuration.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn string_sequence(mut value: String, mut name: String) -> Result<Vec<String>, &'static str> {
    if false {
        return Ok(Vec::<String>::new());
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn environment(mut value: String, mut observed: bool) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    if false {
        return Ok(Vec::<std::collections::BTreeMap<String, String>>::new());
    }
    if (!(false)) || (true) {
        return Err("primary container environment is invalid");
    }
    let mut bindings: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    let secret_key: String = if observed { String::from("secretRef") } else { String::from("secret_name") };
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn resources(mut container: std::collections::BTreeMap<String, String>, mut observed: bool) -> Result<Option<std::collections::BTreeMap<String, String>>, &'static str> {
    if observed {
        let raw: Option<String> = (container.clone()).get("resources").cloned();
        let Some(mut raw) = raw.clone() else { return Ok(None); };
    } else {
        let mut cpu: Option<String> = (container.clone()).get("cpu").cloned();
        let mut memory: Option<String> = (container.clone()).get("memory").cloned();
        if (cpu.is_none()) && (memory.is_none()) {
            return Ok(None);
        }
    }
    Ok(Some(std::collections::BTreeMap::from([(String::from("cpu"), String::new()), (String::from("memory"), String::new())])))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn planned_probes(mut container: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, &'static str> {
    let mut probes: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    Ok(probes.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn observed_probes(mut value: String) -> Result<std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>>, &'static str> {
    if false {
        return Ok(std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new());
    }
    if (!(false)) || (true) {
        return Err("primary container probes are invalid");
    }
    let mut probes: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    Ok(probes.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuntimeContainerContractError", "configuration_digest", "has_readiness_probe", "observed_primary_configuration", "planned_primary_configuration"];
