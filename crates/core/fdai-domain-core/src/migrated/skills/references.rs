pub const MAX_REFERENCE_COUNT: i64 = 16;
pub const MAX_REFERENCE_BYTES: i64 = 262144;
pub const MAX_REFERENCE_TOTAL_BYTES: i64 = 1048576;
pub const MAX_REFERENCE_PATH_CHARS: i64 = 255;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillReferenceManifest {
    pub path: String,
    pub sha256: String,
    pub size_bytes: i64,
    pub media_type: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillReferenceArtifact {
    pub manifest: Box<SkillReferenceManifest>,
    pub content: Vec<u8>,
}

pub const SHA256_PATTERN: &str = "^[a-f0-9]{64}$";
pub const PATH_SEGMENT_PATTERN: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_reference_manifest(mut references: Vec<SkillReferenceManifest>) -> Result<(), &'static str> {
    if (((references.clone()).len() as i64)) > (MAX_REFERENCE_COUNT) {
        return Err("skill references MUST NOT contain more than 16 entries");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_reference_declaration(mut path: String, mut sha256: String, mut size_bytes: i64, mut media_type: String) -> Result<(), &'static str> {
    let parts: Vec<String> = (path.clone()).split("/").map(str::to_string).collect::<Vec<String>>();
    if ((size_bytes) < (0_i64)) || ((size_bytes) > (MAX_REFERENCE_BYTES)) {
        return Err("skill reference size_bytes MUST be between 0 and 256 KiB");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_reference_artifacts(mut declarations: Vec<SkillReferenceManifest>, mut references: std::collections::BTreeMap<String, Vec<u8>>) -> Result<Vec<SkillReferenceArtifact>, &'static str> {
    let mut artifacts: Vec<SkillReferenceArtifact> = Vec::<SkillReferenceArtifact>::new();
    for declaration in declarations.clone() {
        artifacts.push(SkillReferenceArtifact { manifest: Box::new(declaration.clone()), ..Default::default() });
    }
    Ok(artifacts.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_reference_artifacts(mut declarations: Vec<SkillReferenceManifest>, mut artifacts: Vec<SkillReferenceArtifact>) -> Result<(), &'static str> {
    let rebuilt: Vec<SkillReferenceArtifact> = build_reference_artifacts(declarations.clone(), std::collections::BTreeMap::new()).unwrap_or_else(|_| Vec::new());
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["MAX_REFERENCE_COUNT", "SkillReferenceArtifact", "SkillReferenceManifest", "build_reference_artifacts", "validate_reference_declaration", "validate_reference_manifest", "verify_reference_artifacts"];
