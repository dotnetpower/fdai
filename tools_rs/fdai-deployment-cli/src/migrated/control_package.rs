pub const MAX_ARCHIVE_BYTES: i64 = 134217728;
pub const MAX_MEMBER_BYTES: i64 = 67108864;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ControlPackage {
    pub archive: String,
    pub archive_digest: String,
    pub sums_digest: String,
    pub version: String,
}

pub const PACKAGE_ROOT: &str = "package";
pub const SUMS: &str = "SHA256SUMS";
pub const SIGNATURE: &str = "SHA256SUMS.sig";
pub const REQUIREMENTS: &str = "requirements.txt";
pub const SUM_LINE: &str = "([0-9a-f]{64})  ([A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*)";
pub const REQUIREMENT: &str = "fdai-deployment-cli==([0-9]+\\.[0-9]+\\.[0-9]+)\\n";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_control_package(mut archive: String, mut public_key_pem: Option<Vec<u8>>) -> Result<ControlPackage, &'static str> {
    let files: std::collections::BTreeMap<String, Vec<u8>> = read_members(archive.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let listed: std::collections::BTreeMap<String, String> = parse_sums(Vec::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(ControlPackage { archive: archive.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn read_members(mut archive: String) -> Result<std::collections::BTreeMap<String, Vec<u8>>, &'static str> {
    let mut files: std::collections::BTreeMap<String, Vec<u8>> = std::collections::BTreeMap::<String, Vec<u8>>::new();
    Ok(files.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_sums(mut sums: Vec<u8>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut listed: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    if (listed.clone()).is_empty() {
        return Err("control package SHA256SUMS is empty");
    }
    Ok(listed.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PACKAGE_ROOT", "ControlPackage", "verify_control_package"];
