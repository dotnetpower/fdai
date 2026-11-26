#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OntologyDeclarationKind {
    #[default]
    Object,
    Link,
    Action,
    Interface,
    Function,
}

impl OntologyDeclarationKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Object => "object",
            Self::Link => "link",
            Self::Action => "action",
            Self::Interface => "interface",
            Self::Function => "function",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyDeclarationRef {
    pub kind: OntologyDeclarationKind,
    pub name: String,
    pub version: String,
    pub declaration_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyTypeRef {
    pub kind: OntologyDeclarationKind,
    pub name: String,
    pub version: String,
    pub catalog_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyReleaseRef {
    pub schema_version: String,
    pub digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OntologyRelease {
    pub schema_version: String,
    pub digest: String,
    pub declarations: Vec<OntologyDeclarationRef>,
}

pub const DIGEST_PATTERN: &str = "^sha256:[a-f0-9]{64}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ContractBase {
    pub initialized: bool,
}

impl OntologyRelease {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn content_is_canonical(&self) -> OntologyRelease {
        core::hint::black_box(Default::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn r#ref(&self) -> OntologyReleaseRef {
        OntologyReleaseRef { schema_version: self.schema_version.clone(), digest: self.digest.clone(), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn type_ref(&self, mut kind: OntologyDeclarationKind, mut name: String) -> Result<OntologyTypeRef, &'static str> {
        Err("ontology release has no kind.value declaration namer")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ContractBase", "IdempotencyKey", "OntologyDeclarationKind", "OntologyDeclarationRef", "OntologyRelease", "OntologyReleaseRef", "OntologyTypeRef", "SemVer", "_Base"];
