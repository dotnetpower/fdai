pub const MAX_CONFIGURATION_ARTIFACT_BYTES: i64 = 2097152;

pub const CONFIGURATION_FILE_FORMAT: &str = "fdai.lifecycle-configuration-file.v1";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn configuration_artifact_bytes(mut package: String) -> Vec<u8> {
    if package.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn read_configuration_artifact(mut content: Vec<u8>) -> Result<String, &'static str> {
    if (((content.clone()).len() as i64)) > (MAX_CONFIGURATION_ARTIFACT_BYTES) {
        return Err("configuration artifact exceeds its byte bound");
    }
    Ok(String::new())
}

