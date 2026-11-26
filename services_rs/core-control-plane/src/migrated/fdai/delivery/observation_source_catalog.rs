pub const MAX_CATALOG_BYTES: i64 = 256000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObservationSourceCatalog {
    pub version: i64,
    pub max_concurrency: i64,
    pub sources: Vec<String>,
    pub digest: String,
}

pub const CATALOG_KEYS: &[&str] = &["version", "max_concurrency", "sources"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_observation_source_catalog(mut path: String) -> Result<ObservationSourceCatalog, &'static str> {
    let _ = require_exact_keys(std::collections::BTreeMap::new(), std::collections::BTreeSet::new(), String::from("catalog")).unwrap_or_else(|_| ());
    let version: i64 = integer(String::new(), String::from("version")).unwrap_or_else(|_| 0_i64);
    if (version) != (1_i64) {
        return Err("observation source catalog version MUST be 1");
    }
    let max_concurrency: i64 = integer(String::new(), String::from("max_concurrency")).unwrap_or_else(|_| 0_i64);
    if !(((1_i64) <= (max_concurrency)) && ((max_concurrency) <= (4_i64))) {
        return Err("observation source max_concurrency MUST be in 1 4");
    }
    Ok(ObservationSourceCatalog { version: version, max_concurrency: max_concurrency, ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn source(mut value: String) -> Result<String, &'static str> {
    if !(false) {
        return Err("observation source entry MUST be an object");
    }
    let _ = require_exact_keys(std::collections::BTreeMap::new(), std::collections::BTreeSet::new(), String::from("source entry")).unwrap_or_else(|_| ());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: String, mut field: String) -> Result<String, &'static str> {
    if (!(true)) || ((value.trim().to_string()).is_empty()) {
        return Err("observation source field MUST be non-empty text");
    }
    Ok(value.trim().to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut value: String, mut field: String) -> Result<i64, &'static str> {
    if (!(false)) || (false) {
        return Err("observation source field MUST be an integer");
    }
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn number(mut value: String, mut field: String) -> Result<f64, &'static str> {
    if (!(true)) || (false) {
        return Err("observation source field MUST be numeric");
    }
    Ok((value.clone()).trim().parse::<f64>().unwrap_or(0.0))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_exact_keys(mut value: std::collections::BTreeMap<String, String>, mut allowed: std::collections::BTreeSet<String>, mut field: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ObservationSourceCatalog", "load_observation_source_catalog"];
