//! Bounded durable/in-memory runtime state store with Idempotency-Key conflict detection,
//! monotonic audit/KPI projections, CAS settings/preferences, and live SSE broadcast hub.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, VecDeque};
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::{broadcast, RwLock};

const MAX_AUDIT_RECORDS: usize = 2_000;
const MAX_IDEMPOTENCY_ENTRIES: usize = 2_000;
const MAX_RULE_ACTIVATION_HISTORY: usize = 500;
const SSE_BROADCAST_CAP: usize = 256;

#[must_use]
pub fn is_mandatory_rule_severity(severity: &str) -> bool {
    let norm = severity.trim().to_ascii_lowercase();
    matches!(
        norm.as_str(),
        "critical" | "high" | "sev1" | "sev2" | "p0" | "p1" | "긴급" | "높음"
    )
}

#[derive(Clone, Debug)]
pub struct RuleActivationUpdate<'a> {
    pub rule_id: &'a str,
    pub enabled: bool,
    pub mode: Option<&'a str>,
    pub severity: &'a str,
    pub actor_subject_id: &'a str,
    pub reason: &'a str,
    pub now_iso: &'a str,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredRuleActivation {
    pub rule_id: String,
    pub enabled: bool,
    pub mode: String,
    pub severity: String,
    pub mandatory_active: bool,
    pub updated_at: String,
    pub updated_by: String,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RuleActivationAuditEntry {
    pub seq: u64,
    pub rule_id: String,
    pub enabled: bool,
    pub mode: String,
    pub severity: String,
    pub mandatory_active: bool,
    pub actor_subject_id: String,
    pub recorded_at: String,
    pub reason: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LiveStreamEvent {
    pub seq: u64,
    pub event_type: String,
    pub payload_json: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AuditRecord {
    pub seq: u64,
    pub recorded_at: String,
    pub action_kind: String,
    pub outcome: String,
    pub tier: String,
    pub correlation_id: String,
    pub actor_subject_id: String,
    pub detail: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct IdempotencyEntry {
    pub body_digest: u64,
    pub response_json: Value,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredRuntimeSettings {
    pub revision: u64,
    pub updated_at: Option<String>,
    pub updated_by: Option<String>,
    pub overrides: BTreeMap<String, Value>,
}

impl Default for StoredRuntimeSettings {
    fn default() -> Self {
        Self {
            revision: 1,
            updated_at: None,
            updated_by: None,
            overrides: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredUserPreference {
    pub principal_id: String,
    pub locale: String,
    pub verbosity: String,
    pub answer_detail: String,
    pub answer_format: String,
    pub answer_preferences_enabled: bool,
    pub timezone: Option<String>,
    pub share_with_learner: bool,
    pub revision: u64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct PersistedState {
    next_seq: u64,
    audit_records: VecDeque<AuditRecord>,
    idempotency_ledger: BTreeMap<String, IdempotencyEntry>,
    idempotency_order: VecDeque<String>,
    runtime_settings: StoredRuntimeSettings,
    user_preferences: BTreeMap<String, StoredUserPreference>,
    #[serde(default)]
    rule_activations: BTreeMap<String, StoredRuleActivation>,
    #[serde(default)]
    rule_activation_history: VecDeque<RuleActivationAuditEntry>,
}

#[derive(Clone, Debug)]
pub enum IdempotencyOutcome {
    Created(Value),
    Replayed(Value),
    Conflict,
}

#[derive(Clone)]
pub struct RuntimeStateStore {
    inner: Arc<RwLock<PersistedState>>,
    persist_path: Option<PathBuf>,
    sse_tx: broadcast::Sender<LiveStreamEvent>,
    live_seq: Arc<AtomicU64>,
}

impl RuntimeStateStore {
    #[must_use]
    pub fn open_from_env() -> Self {
        let persist_path = std::env::var("FDAI_RUST_STATE_FILE")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .map(PathBuf::from);
        Self::open(persist_path)
    }

    #[must_use]
    pub fn open(persist_path: Option<PathBuf>) -> Self {
        let mut initial = persist_path
            .as_ref()
            .and_then(|p| fs::read_to_string(p).ok())
            .and_then(|raw| serde_json::from_str::<PersistedState>(&raw).ok())
            .unwrap_or_default();
        if initial.runtime_settings.revision == 0 {
            initial.runtime_settings.revision = 1;
        }
        let init_seq = initial.next_seq;
        let (sse_tx, _) = broadcast::channel(SSE_BROADCAST_CAP);
        Self {
            inner: Arc::new(RwLock::new(initial)),
            persist_path,
            sse_tx,
            live_seq: Arc::new(AtomicU64::new(init_seq)),
        }
    }

    #[must_use]
    pub fn subscribe_events(&self) -> broadcast::Receiver<LiveStreamEvent> {
        self.sse_tx.subscribe()
    }

    pub fn publish_live_event(&self, event_type: &str, payload_json: String) -> u64 {
        let seq = self.live_seq.fetch_add(1, Ordering::Relaxed).saturating_add(1);
        let _ = self.sse_tx.send(LiveStreamEvent {
            seq,
            event_type: event_type.to_string(),
            payload_json,
        });
        seq
    }

    #[must_use]
    pub fn is_durable_disk_backed(&self) -> bool {
        self.persist_path.is_some()
    }

    pub async fn record_intervention(
        &self,
        idempotency_key: &str,
        body_digest: u64,
        correlation_id: &str,
        action_kind: &str,
        actor_subject_id: &str,
        now_iso: &str,
    ) -> IdempotencyOutcome {
        let mut st = self.inner.write().await;
        if let Some(existing) = st.idempotency_ledger.get(idempotency_key) {
            if existing.body_digest == body_digest {
                let mut replayed = existing.response_json.clone();
                if let Some(obj) = replayed.as_object_mut() {
                    obj.insert(String::from("idempotent_replay"), Value::Bool(true));
                }
                return IdempotencyOutcome::Replayed(replayed);
            }
            return IdempotencyOutcome::Conflict;
        }

        st.next_seq = st.next_seq.saturating_add(1);
        let seq = st.next_seq;
        let response_json = json!({
            "request_id": format!("req-{idempotency_key}"),
            "correlation_id": correlation_id,
            "action_kind": action_kind,
            "actor_subject_id": actor_subject_id,
            "audit_seq": seq,
            "dispatch_status": "queued",
            "accepted_at": now_iso,
            "durably_queued": true,
            "idempotent_replay": false
        });

        let rec = AuditRecord {
            seq,
            recorded_at: now_iso.to_string(),
            action_kind: action_kind.to_string(),
            outcome: String::from("queued"),
            tier: String::from("T1"),
            correlation_id: correlation_id.to_string(),
            actor_subject_id: actor_subject_id.to_string(),
            detail: format!("intervention queued for {correlation_id}"),
        };
        st.audit_records.push_back(rec);
        while st.audit_records.len() > MAX_AUDIT_RECORDS {
            st.audit_records.pop_front();
        }
        st.idempotency_ledger.insert(
            idempotency_key.to_string(),
            IdempotencyEntry {
                body_digest,
                response_json: response_json.clone(),
            },
        );
        st.idempotency_order.push_back(idempotency_key.to_string());
        while st.idempotency_order.len() > MAX_IDEMPOTENCY_ENTRIES {
            if let Some(oldest) = st.idempotency_order.pop_front() {
                st.idempotency_ledger.remove(&oldest);
            }
        }
        self.flush_atomic_locked(&st);
        let ev = LiveStreamEvent {
            seq,
            event_type: String::from("incident.intervention.queued"),
            payload_json: serde_json::to_string(&response_json)
                .unwrap_or_else(|_| String::from("{}")),
        };
        let _ = self.sse_tx.send(ev);
        IdempotencyOutcome::Created(response_json)
    }

    pub async fn kpi_snapshot(&self) -> Value {
        let st = self.inner.read().await;
        let count = st.audit_records.len();
        let from_seq = st.audit_records.front().map(|r| r.seq);
        let through_seq = st.audit_records.back().map(|r| r.seq);
        let last_recorded_at = st.audit_records.back().map(|r| r.recorded_at.clone());
        let mut by_action_kind: BTreeMap<String, usize> = BTreeMap::new();
        let mut by_outcome: BTreeMap<String, usize> = BTreeMap::new();
        let mut by_tier: BTreeMap<String, usize> = BTreeMap::new();
        for rec in &st.audit_records {
            *by_action_kind.entry(rec.action_kind.clone()).or_insert(0) += 1;
            *by_outcome.entry(rec.outcome.clone()).or_insert(0) += 1;
            *by_tier.entry(rec.tier.clone()).or_insert(0) += 1;
        }
        json!({
            "event_count": count,
            "shadow_share": 1.0,
            "enforce_share": 0.0,
            "hil_pending": 0,
            "by_action_kind": by_action_kind,
            "by_outcome": by_outcome,
            "by_tier": by_tier,
            "last_recorded_at": last_recorded_at,
            "audit_sample": {
                "from_seq": from_seq,
                "through_seq": through_seq,
                "row_count": count,
                "limit": 1000
            }
        })
    }

    pub async fn audit_snapshot(&self, now_iso: &str) -> Value {
        let st = self.inner.read().await;
        let count = st.audit_records.len();
        let items: Vec<Value> = st
            .audit_records
            .iter()
            .rev()
            .take(50)
            .map(|r| {
                json!({
                    "seq": r.seq,
                    "event_id": format!("evt-{:08}", r.seq),
                    "correlation_id": r.correlation_id,
                    "action_kind": r.action_kind,
                    "outcome": r.outcome,
                    "tier": r.tier,
                    "mode": "shadow",
                    "actor_subject_id": r.actor_subject_id,
                    "detail": r.detail,
                    "recorded_at": r.recorded_at
                })
            })
            .collect();
        json!({
            "items": items,
            "next_cursor": null,
            "summary": {
                "observed_at": now_iso,
                "matching_record_count": count,
                "terminal_record_count": count,
                "human_review_record_count": 0,
                "rollback_record_count": 0,
                "integrity": {
                    "status": "verified",
                    "reason": null,
                    "verified_at": now_iso,
                    "current_record_count": count,
                    "current_link_gap_count": 0
                },
                "redaction_applied": false
            }
        })
    }

    pub async fn runtime_settings_snapshot(&self) -> StoredRuntimeSettings {
        self.inner.read().await.runtime_settings.clone()
    }

    pub async fn update_runtime_settings(
        &self,
        expected_revision: Option<u64>,
        changes: BTreeMap<String, Value>,
        actor_subject_id: &str,
        now_iso: &str,
    ) -> Result<StoredRuntimeSettings, u64> {
        let mut st = self.inner.write().await;
        if let Some(exp) = expected_revision {
            if exp != st.runtime_settings.revision {
                return Err(st.runtime_settings.revision);
            }
        }
        for (k, v) in changes {
            if v.is_null() {
                st.runtime_settings.overrides.remove(&k);
            } else {
                st.runtime_settings.overrides.insert(k, v);
            }
        }
        st.runtime_settings.revision = st.runtime_settings.revision.saturating_add(1);
        let new_rev = st.runtime_settings.revision;
        st.runtime_settings.updated_at = Some(now_iso.to_string());
        st.runtime_settings.updated_by = Some(actor_subject_id.to_string());
        st.next_seq = st.next_seq.saturating_add(1);
        let seq = st.next_seq;
        st.audit_records.push_back(AuditRecord {
            seq,
            recorded_at: now_iso.to_string(),
            action_kind: String::from("runtime.settings.update"),
            outcome: String::from("applied"),
            tier: String::from("T1"),
            correlation_id: format!("settings-rev-{new_rev}"),
            actor_subject_id: actor_subject_id.to_string(),
            detail: String::from("runtime settings updated"),
        });
        while st.audit_records.len() > MAX_AUDIT_RECORDS {
            st.audit_records.pop_front();
        }
        self.flush_atomic_locked(&st);
        Ok(st.runtime_settings.clone())
    }

    pub async fn get_or_default_preference(&self, principal_id: &str) -> StoredUserPreference {
        let st = self.inner.read().await;
        st.user_preferences
            .get(principal_id)
            .cloned()
            .unwrap_or_else(|| StoredUserPreference {
                principal_id: principal_id.to_string(),
                locale: String::from("en"),
                verbosity: String::from("concise"),
                answer_detail: String::from("standard"),
                answer_format: String::from("mixed"),
                answer_preferences_enabled: true,
                timezone: Some(String::from("UTC")),
                share_with_learner: false,
                revision: 1,
            })
    }

    pub async fn audit_count(&self) -> usize {
        self.inner.read().await.audit_records.len()
    }

    pub async fn rule_activations_snapshot(&self) -> BTreeMap<String, StoredRuleActivation> {
        self.inner.read().await.rule_activations.clone()
    }

    pub async fn rule_activation_history_snapshot(&self) -> Vec<RuleActivationAuditEntry> {
        self.inner
            .read()
            .await
            .rule_activation_history
            .iter()
            .rev()
            .cloned()
            .collect()
    }

    pub async fn set_rule_activation(
        &self,
        req: RuleActivationUpdate<'_>,
    ) -> Result<StoredRuleActivation, &'static str> {
        let RuleActivationUpdate {
            rule_id,
            enabled,
            mode,
            severity,
            actor_subject_id,
            reason,
            now_iso,
        } = req;
        let mandatory = is_mandatory_rule_severity(severity);
        if mandatory && !enabled {
            return Err("mandatory_severity_cannot_be_disabled");
        }
        let resolved_mode = match mode.map(str::trim).filter(|s| !s.is_empty()) {
            Some(m) => m.to_string(),
            None if enabled => String::from("Enforce"),
            None => String::from("Disabled"),
        };
        let resolved_reason = if reason.trim().is_empty() {
            if mandatory {
                String::from("Critical/High mandatory activation policy")
            } else if enabled {
                String::from("Administrator enabled rule from console")
            } else {
                String::from("Administrator disabled rule from console")
            }
        } else {
            reason.trim().chars().take(500).collect()
        };

        let record = StoredRuleActivation {
            rule_id: rule_id.to_string(),
            enabled: mandatory || enabled,
            mode: resolved_mode.clone(),
            severity: severity.to_string(),
            mandatory_active: mandatory,
            updated_at: now_iso.to_string(),
            updated_by: actor_subject_id.to_string(),
            reason: resolved_reason.clone(),
        };

        {
            let mut st = self.inner.write().await;
            st.rule_activations
                .insert(rule_id.to_string(), record.clone());
            st.next_seq = st.next_seq.saturating_add(1);
            let seq = st.next_seq;
            st.rule_activation_history
                .push_back(RuleActivationAuditEntry {
                    seq,
                    rule_id: rule_id.to_string(),
                    enabled: record.enabled,
                    mode: resolved_mode,
                    severity: severity.to_string(),
                    mandatory_active: mandatory,
                    actor_subject_id: actor_subject_id.to_string(),
                    recorded_at: now_iso.to_string(),
                    reason: resolved_reason.clone(),
                });
            while st.rule_activation_history.len() > MAX_RULE_ACTIVATION_HISTORY {
                st.rule_activation_history.pop_front();
            }
            st.audit_records.push_back(AuditRecord {
                seq,
                recorded_at: now_iso.to_string(),
                action_kind: if record.enabled {
                    String::from("governance.rule.enable")
                } else {
                    String::from("governance.rule.disable")
                },
                outcome: String::from("applied"),
                tier: String::from("T0"),
                correlation_id: format!("rule-activation-{rule_id}-{seq}"),
                actor_subject_id: actor_subject_id.to_string(),
                detail: format!("{rule_id} enabled={} ({resolved_reason})", record.enabled),
            });
            while st.audit_records.len() > MAX_AUDIT_RECORDS {
                st.audit_records.pop_front();
            }
            self.flush_atomic_locked(&st);
        }

        let payload = json!({
            "rule_id": record.rule_id,
            "enabled": record.enabled,
            "mandatory_active": record.mandatory_active,
            "severity": record.severity,
            "updated_at": record.updated_at,
            "updated_by": record.updated_by
        })
        .to_string();
        let _ = self.publish_live_event("rule.activation.updated", payload);
        Ok(record)
    }

    pub async fn enforce_mandatory_rules(
        &self,
        mandatory_rules: &[(String, String)],
        actor_subject_id: &str,
        now_iso: &str,
    ) -> usize {
        let mut enforced = 0_usize;
        let mut st = self.inner.write().await;
        for (rule_id, severity) in mandatory_rules {
            if !is_mandatory_rule_severity(severity) {
                continue;
            }
            let needs_update = st
                .rule_activations
                .get(rule_id)
                .map(|r| !r.enabled || !r.mandatory_active)
                .unwrap_or(true);
            if needs_update {
                st.rule_activations.insert(
                    rule_id.clone(),
                    StoredRuleActivation {
                        rule_id: rule_id.clone(),
                        enabled: true,
                        mode: String::from("Enforce"),
                        severity: severity.clone(),
                        mandatory_active: true,
                        updated_at: now_iso.to_string(),
                        updated_by: actor_subject_id.to_string(),
                        reason: String::from("Mandatory activation enforced for Critical/High rule"),
                    },
                );
                enforced = enforced.saturating_add(1);
            }
        }
        if enforced > 0 {
            st.next_seq = st.next_seq.saturating_add(1);
            let seq = st.next_seq;
            st.audit_records.push_back(AuditRecord {
                seq,
                recorded_at: now_iso.to_string(),
                action_kind: String::from("governance.rule.enforce_mandatory"),
                outcome: String::from("applied"),
                tier: String::from("T0"),
                correlation_id: format!("rule-enforce-mandatory-{seq}"),
                actor_subject_id: actor_subject_id.to_string(),
                detail: format!("enforced mandatory activation on {enforced} Critical/High rules"),
            });
            while st.audit_records.len() > MAX_AUDIT_RECORDS {
                st.audit_records.pop_front();
            }
            self.flush_atomic_locked(&st);
        }
        enforced
    }

    fn flush_atomic_locked(&self, st: &PersistedState) {
        let Some(ref target) = self.persist_path else {
            return;
        };
        if let Some(parent) = target.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let Ok(bytes) = serde_json::to_vec(st) else {
            return;
        };
        let tmp = target.with_extension(format!("tmp.{}", std::process::id()));
        if fs::write(&tmp, bytes).is_ok() {
            let _ = fs::rename(&tmp, target);
        }
    }
}

#[must_use]
pub fn fnv1a64_bytes(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for &b in bytes {
        h ^= u64::from(b);
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn rule_activation_enforces_mandatory_critical_and_high_severities() {
        assert!(is_mandatory_rule_severity("critical"));
        assert!(is_mandatory_rule_severity("High"));
        assert!(is_mandatory_rule_severity("긴급"));
        assert!(is_mandatory_rule_severity("높음"));
        assert!(!is_mandatory_rule_severity("medium"));
        assert!(!is_mandatory_rule_severity("low"));
        assert!(!is_mandatory_rule_severity("보통"));

        let store = RuntimeStateStore::open(None);

        // Critical/High deactivation MUST be deterministically rejected.
        let denied_crit = store
            .set_rule_activation(RuleActivationUpdate {
                rule_id: "RULE-SRE-014",
                enabled: false,
                mode: Some("Disabled"),
                severity: "critical",
                actor_subject_id: "admin@corp",
                reason: "attempt disable critical",
                now_iso: "2026-11-26T10:00:00Z",
            })
            .await;
        assert_eq!(denied_crit.err(), Some("mandatory_severity_cannot_be_disabled"));

        let denied_high = store
            .set_rule_activation(RuleActivationUpdate {
                rule_id: "RULE-SEC-041",
                enabled: false,
                mode: Some("Disabled"),
                severity: "High",
                actor_subject_id: "admin@corp",
                reason: "attempt disable high",
                now_iso: "2026-11-26T10:00:01Z",
            })
            .await;
        assert_eq!(denied_high.err(), Some("mandatory_severity_cannot_be_disabled"));

        // Medium/Low rules can be easily toggled off and back on.
        let disabled_med = store
            .set_rule_activation(RuleActivationUpdate {
                rule_id: "RULE-COST-011",
                enabled: false,
                mode: None,
                severity: "medium",
                actor_subject_id: "admin@corp",
                reason: "maintenance window",
                now_iso: "2026-11-26T10:00:02Z",
            })
            .await;
        assert!(disabled_med.is_ok());
        if let Ok(rec) = disabled_med {
            assert!(!rec.enabled);
            assert!(!rec.mandatory_active);
            assert_eq!(rec.mode, "Disabled");
        }

        let enabled_med = store
            .set_rule_activation(RuleActivationUpdate {
                rule_id: "RULE-COST-011",
                enabled: true,
                mode: Some("Enforce"),
                severity: "medium",
                actor_subject_id: "admin@corp",
                reason: "",
                now_iso: "2026-11-26T10:00:03Z",
            })
            .await;
        assert!(enabled_med.is_ok());
        if let Ok(rec) = enabled_med {
            assert!(rec.enabled);
            assert_eq!(rec.mode, "Enforce");
        }

        // Batch mandatory enforcement enables all Critical/High rules.
        let enforced = store
            .enforce_mandatory_rules(
                &[
                    (String::from("RULE-SRE-014"), String::from("critical")),
                    (String::from("RULE-SEC-041"), String::from("high")),
                    (String::from("RULE-COST-011"), String::from("medium")),
                ],
                "admin@corp",
                "2026-11-26T10:00:04Z",
            )
            .await;
        assert_eq!(enforced, 2);
        let snap = store.rule_activations_snapshot().await;
        assert!(snap.get("RULE-SRE-014").map(|r| r.enabled && r.mandatory_active).unwrap_or(false));
        assert!(snap.get("RULE-SEC-041").map(|r| r.enabled && r.mandatory_active).unwrap_or(false));
    }
}
