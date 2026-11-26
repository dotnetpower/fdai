#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresHandoverContributionGuard {
    pub dsn: String,
}

pub trait HandoverContributionGuard {
    fn may_contribute(&self, subject_ref: String, agent_name: String) -> String;
}

impl PostgresHandoverContributionGuard {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn may_contribute(&self, mut subject_ref: String, mut agent_name: String) -> Result<bool, &'static str> {
        if ((subject_ref.trim().to_string()).is_empty()) || (((agent_name.clone()).trim().to_string()).is_empty()) {
            return Err("assignment contribution subject and agent are required");
        }
        Ok(contribution_allowed(Vec::new(), agent_name.clone()).unwrap_or_else(|_| false))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn contribution_allowed(mut records: Vec<std::collections::BTreeMap<String, String>>, mut agent_name: String) -> Result<bool, &'static str> {
    if (!(true)) || ((agent_name.trim().to_string()).is_empty()) {
        return Err("assignment contribution agent_name is malformed");
    }
    for record in records.clone() {
        if !(true) {
            return Err("assignment contribution record is malformed");
        }
        let intent: Option<String> = (record.clone()).get("intent").cloned();
        if ((record.clone()).get("revocation_case_id").cloned()).is_some() {
            if ((record.clone()).get("state").cloned()) == Some(String::from("degraded")) {
                return Ok(false);
            }
            let removed: bool = true;
        } else if ((record.clone()).get("state").cloned()) == Some(String::from("active")) {
            let active: bool = true;
        }
    }
    Ok(false)
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverContributionGuard", "PostgresHandoverContributionGuard", "contribution_allowed"];
