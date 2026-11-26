pub const UUID: &str = "[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}";
pub const SEGMENT: &str = "[A-Za-z0-9._()-]+";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn image_requirements(mut image: String, mut subscription_id: String, mut region: String, mut capture: String, mut cwd: String, mut environment: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if !((image.to_lowercase()).contains("/galleries/")) {
        if (location(String::new()).unwrap_or_else(|_| String::new())) != (location(region.clone()).unwrap_or_else(|_| String::new())) {
            return Err("EVIDENCE_INVALID 3");
        }
    } else {
        let mut matches: Vec<String> = Vec::<String>::new();
    }
    Ok(std::collections::BTreeMap::from([(String::from("diskSizeGB"), String::new()), (String::from("hyperVGeneration"), String::from("V2")), (String::from("osType"), String::from("Linux"))]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn location(mut value: String) -> Result<String, &'static str> {
    Ok(((value.clone()).replace(" ", "")).to_lowercase())
}

