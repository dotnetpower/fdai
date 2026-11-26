use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleActivationRecordKind {
    #[default]
    Proposal,
    Change,
    Approval,
    Command,
    ResultContract,
    Request,
    Pointer,
    Generation,
    Idempotency,
    Manifest,
    Prepare,
    Acknowledgement,
}

impl RuleActivationRecordKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Proposal => "rule_activation.proposal",
            Self::Change => "rule_activation.change",
            Self::Approval => "rule_activation.approval",
            Self::Command => "rule_activation.command",
            Self::ResultContract => "rule_activation.result",
            Self::Request => "rule_activation.request",
            Self::Pointer => "rule_activation.current",
            Self::Generation => "rule_activation.generation",
            Self::Idempotency => "rule_activation.idempotency",
            Self::Manifest => "rule_activation.manifest",
            Self::Prepare => "rule_activation.prepare",
            Self::Acknowledgement => "rule_activation.acknowledgement",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DecodedRuleActivationRecord {
    pub schema_version: String,
    pub kind: RuleActivationRecordKind,
    pub body: BTreeMap<String, String>,
}

pub const RULE_ACTIVATION_WRITE_SCHEMA_VERSION: &str = "1.0.0";
pub const RULE_ACTIVATION_READ_SCHEMA_VERSIONS: &[&str] = &["1.0.0", "2.0.0"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn encode_rule_activation_record(mut kind: RuleActivationRecordKind, mut body: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from(RULE_ACTIVATION_WRITE_SCHEMA_VERSION)), (String::from("kind"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn decode_rule_activation_record(mut value: std::collections::BTreeMap<String, String>, mut expected_kind: RuleActivationRecordKind) -> Result<DecodedRuleActivationRecord, &'static str> {
    let raw: std::collections::BTreeMap<String, String> = body(value.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(DecodedRuleActivationRecord { kind: expected_kind.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn canonicalize_rule_activation_payload(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut raw: std::collections::BTreeMap<String, String> = body(value.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let schema_version: String = (raw.clone()).get("schema_version").cloned().unwrap_or_else(|| String::from(RULE_ACTIVATION_WRITE_SCHEMA_VERSION));
    raw.insert(String::from("schema_version"), String::from(RULE_ACTIVATION_WRITE_SCHEMA_VERSION));
    Ok(raw.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn canonicalize_rule_activation_typed_payload(mut kind: RuleActivationRecordKind, mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut raw: std::collections::BTreeMap<String, String> = canonicalize_rule_activation_payload(value.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Ok(raw.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn body(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DecodedRuleActivationRecord", "RULE_ACTIVATION_READ_SCHEMA_VERSIONS", "RULE_ACTIVATION_WRITE_SCHEMA_VERSION", "RuleActivationRecordKind", "canonicalize_rule_activation_payload", "canonicalize_rule_activation_typed_payload", "decode_rule_activation_record", "encode_rule_activation_record"];
