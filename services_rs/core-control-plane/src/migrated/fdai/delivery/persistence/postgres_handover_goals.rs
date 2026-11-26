#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresHandoverGoalReader {
    pub config: String,
}

impl PostgresHandoverGoalReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_page(&self, mut limit: i64, mut offset: i64) -> Result<(Vec<std::collections::BTreeMap<String, String>>, i64), &'static str> {
        if (false) || ((!(true)) || ((!(((1_i64) <= (limit)) && ((limit) <= (1000_i64)))) || ((false) || ((!(true)) || ((offset) < (0_i64)))))) {
            return Err("handover projection page bounds are invalid");
        }
        Ok((Vec::new(), 0_i64))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn project(mut value: String) -> std::collections::BTreeMap<String, String> {
    if !(false) {
        return std::collections::BTreeMap::<String, String>::new();
    }
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresHandoverGoalReader"];
