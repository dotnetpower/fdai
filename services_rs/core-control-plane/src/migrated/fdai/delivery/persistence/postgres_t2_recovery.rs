#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresT2RecoveryLegacyReader {
    pub initialized: bool,
}

impl PostgresT2RecoveryLegacyReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_failures(&self, mut limit: i64) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
        if !(((1_i64) <= (limit)) && ((limit) <= (1000_i64))) {
            return Err("T2 recovery legacy read limit MUST be in 1 1000");
        }
        Ok(Vec::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresT2RecoveryLegacyReader"];
