use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum VerticalAssetKind {
    #[default]
    Policy,
    Remediation,
    Rule,
    SemanticProfile,
    Workflow,
}

impl VerticalAssetKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Policy => "policy",
            Self::Remediation => "remediation",
            Self::Rule => "rule",
            Self::SemanticProfile => "semantic_profile",
            Self::Workflow => "workflow",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalAssetDeclaration {
    pub asset_id: String,
    pub kind: VerticalAssetKind,
    pub resource_path: String,
    pub sha256: String,
    pub references: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalPackageAsset {
    pub declaration: Box<VerticalAssetDeclaration>,
    pub content: Vec<u8>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalProviderDeclaration {
    pub binding_id: String,
    pub protocol: String,
    pub required: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalPackageManifest {
    pub extension: String,
    pub vertical_id: String,
    pub asset_manifest_sha256: String,
    pub ontology_release_range: String,
    pub semantic_profile_sha256: String,
    pub required_provider_bindings: Vec<String>,
    pub capability_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalPackageBundle {
    pub descriptor: String,
    pub manifest: Box<VerticalPackageManifest>,
    pub asset_manifest: Vec<u8>,
    pub semantic_profile: Vec<u8>,
    pub assets: Vec<VerticalPackageAsset>,
    pub providers: Vec<VerticalProviderDeclaration>,
    pub capability_bundle: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalPackageAvailability {
    pub available: bool,
    pub reasons: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalPackageRelease {
    pub bundle: Box<VerticalPackageBundle>,
    pub availability: Box<VerticalPackageAvailability>,
    pub image_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InstalledVerticalPackage {
    pub state: String,
    #[allow(clippy::type_complexity)]
    pub previous_release: Option<Box<VerticalPackageRelease>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalPackageActivationMetadata {
    pub vertical_id: String,
    pub package_id: String,
    pub available: bool,
    pub enabled: bool,
    pub availability_reasons: Vec<String>,
    pub package_version: String,
    pub image_digest: String,
    pub asset_manifest_digest: String,
    pub semantic_profile_digest: String,
    pub ontology_release_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerticalPackageRuntime {
    pub packages: BTreeMap<String, VerticalPackageBundle>,
    pub assets: BTreeMap<String, VerticalPackageAsset>,
}

pub const ID_PATTERN: &str = "^[a-z0-9][a-z0-9._:/-]{1,191}$";
pub const SHA256_PATTERN: &str = "^[a-f0-9]{64}$";
pub const PROFILE_SHA256_PATTERN: &str = "^sha256:[a-f0-9]{64}$";
impl VerticalPackageRuntime {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn package_ids(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn asset_ids(&self) -> Vec<String> {
        core::hint::black_box(Vec::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerticalPackageValidationError {
    pub message: String,
}

impl VerticalPackageValidationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VerticalPackageValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VerticalPackageValidationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerticalPackageLifecycleError {
    pub message: String,
}

impl VerticalPackageLifecycleError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VerticalPackageLifecycleError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VerticalPackageLifecycleError {}

pub const PUBLIC_EXPORTS: &[&str] = &["InstalledVerticalPackage", "VerticalAssetDeclaration", "VerticalAssetKind", "VerticalPackageAsset", "VerticalPackageActivationMetadata", "VerticalPackageAvailability", "VerticalPackageBundle", "VerticalPackageLifecycleError", "VerticalPackageManifest", "VerticalPackageRelease", "VerticalPackageRuntime", "VerticalPackageValidationError", "VerticalProviderDeclaration"];
