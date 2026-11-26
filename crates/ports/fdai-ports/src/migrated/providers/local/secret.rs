#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EnvSecretProvider {
    pub initialized: bool,
}

impl EnvSecretProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut name: String) -> Result<String, &'static str> {
        Err("secret namer is not defined in EnvSecretProvider")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["EnvSecretProvider"];
