pub const MAX_WIRE_BYTES: i64 = 262144;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProducerCodec {
    pub contract_id: String,
    pub release: String,
    pub schema_version: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConsumerCodec {
    pub contract_id: String,
    pub release: String,
    pub accepted_versions: Vec<String>,
}

impl ProducerCodec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn encode(&self, mut payload: std::collections::BTreeMap<String, String>) -> Vec<u8> {
        encode_wire_object(payload.clone()).unwrap_or_else(|_| Vec::new())
    }
}

impl ConsumerCodec {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn decode(&self, mut encoded: Vec<u8>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        if (((encoded.clone()).len() as i64)) > (MAX_WIRE_BYTES) {
            return Err("encoded service contract exceeds 256 KiB");
        }
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn decode_mapping(&self, mut payload: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
        self.decode(encode_wire_object(payload.clone()).unwrap_or_else(|_| Vec::new())).unwrap_or_else(|_| std::collections::BTreeMap::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn encode_wire_object(mut payload: std::collections::BTreeMap<String, String>) -> Result<Vec<u8>, &'static str> {
    if payload.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn validator() -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConsumerCodec", "MAX_WIRE_BYTES", "ProducerCodec", "encode_wire_object"];
