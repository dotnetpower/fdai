pub mod azure_iam_groups;
pub mod migrated;
pub mod http_compat;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ServiceKind {
    #[default]
    HttpApi,
    EventConsumer,
    ControlPlane,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ServiceDescriptor {
    pub service_id: String,
    pub entrypoint: String,
    pub kind: ServiceKind,
    pub executor_authority: bool,
}

impl ServiceDescriptor {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.service_id.trim().is_empty() || self.entrypoint.trim().is_empty() {
            return Err("service_id and entrypoint must be non-empty");
        }
        if self.service_id == "isolated-executor" && !self.executor_authority {
            return Err("isolated-executor must declare executor_authority");
        }
        if self.service_id != "isolated-executor" && self.executor_authority {
            return Err("only isolated-executor may declare executor_authority");
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RuntimeScopeReceipt {
    pub service_id: String,
    pub venue: String,
    pub executor_authority: bool,
    pub digest_fnv1a: u64,
}

#[must_use]
pub fn canonical_kv_jcs_bytes(pairs: &[(&str, &str)]) -> Vec<u8> {
    let mut sorted: Vec<(&str, &str)> = pairs.to_vec();
    sorted.sort_by_key(|(k, _)| *k);
    let mut s = String::from("{");
    for (idx, (k, v)) in sorted.iter().enumerate() {
        if idx > 0 {
            s.push(',');
        }
        s.push('"');
        s.push_str(k);
        s.push_str("\":\"");
        for ch in v.chars() {
            if ch.is_ascii() && ch != '"' && ch != '\\' && (ch as u32) >= 0x20 {
                s.push(ch);
            } else {
                let mut u16_buf = [0_u16; 2];
                for u in ch.encode_utf16(&mut u16_buf) {
                    s.push_str(&format!("\\u{u:04x}"));
                }
            }
        }
        s.push('"');
    }
    s.push('}');
    s.into_bytes()
}

#[must_use]
pub fn canonical_digest_fnv1a64(bytes: &[u8]) -> u64 {
    bytes.iter().fold(0xcbf29ce484222325_u64, |h, &b| (h ^ u64::from(b)).wrapping_mul(0x100000001b3))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::http_compat::{routing, Router};

    #[test]
    fn validates_executor_jcs_and_multi_method_same_path_router() {
        let ok_exec = ServiceDescriptor {
            service_id: String::from("isolated-executor"),
            entrypoint: String::from("main"),
            kind: ServiceKind::EventConsumer,
            executor_authority: true,
        };
        assert_eq!(ok_exec.validate(), Ok(()));
        let r = Router::new()
            .route("/v1/catalog", routing::get(|| {}).head(|| {}).post(|| {}))
            .nest("/v1/release-hub", Router::new().route("/connection", routing::get(|| {})));
        assert_eq!(r.total_method_bindings(), 4);
    }
}
