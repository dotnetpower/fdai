use std::collections::BTreeMap;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BitemporalSnapshot {
    pub resource_id: String,
    pub as_of: String,
    pub effective: String,
    pub state: BTreeMap<String, String>,
    pub source_seqs: Vec<i64>,
}

impl BitemporalSnapshot {
    #[must_use]
    pub fn as_json(&self) -> BTreeMap<String, String> {
        let state_str = self
            .state
            .iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join(",");
        let seqs_str = self
            .source_seqs
            .iter()
            .map(i64::to_string)
            .collect::<Vec<_>>()
            .join(",");
        BTreeMap::from([
            (String::from("resource_id"), self.resource_id.clone()),
            (String::from("as_of"), self.as_of.clone()),
            (String::from("effective"), self.effective.clone()),
            (String::from("state"), state_str),
            (String::from("source_seqs"), seqs_str),
        ])
    }
}

pub trait BitemporalAuditSource {
    fn read_items(&self, resource_id: String) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BitemporalQueryError {
    pub message: String,
}

impl BitemporalQueryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for BitemporalQueryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for BitemporalQueryError {}

fn extract_field_value(item: &str, key: &str) -> Option<String> {
    let quoted_key = format!("\"{key}\"");
    if let Some(pos) = item.find(&quoted_key) {
        let after = &item[pos + quoted_key.len()..];
        if let Some(colon) = after.find(':') {
            let val_part = after[colon + 1..].trim_start();
            if let Some(stripped) = val_part.strip_prefix('"') {
                if let Some(end_q) = stripped.find('"') {
                    return Some(stripped[..end_q].to_string());
                }
            } else {
                let tok: String = val_part
                    .chars()
                    .take_while(|c| !matches!(c, ',' | '}' | ' ' | '\n' | '\r'))
                    .collect();
                if !tok.is_empty() && tok != "null" {
                    return Some(tok);
                }
            }
        }
    }
    for part in item.split([';', '|', '\n']) {
        let tr = part.trim();
        if let Some((k, v)) = tr.split_once('=') {
            if k.trim() == key {
                let val = v.trim();
                if !val.is_empty() {
                    return Some(val.to_string());
                }
            }
        }
    }
    None
}

fn parse_state_entries(item: &str) -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();
    // 1) Support `"state":{"k":"v",...}` inline object
    if let Some(pos) = item.find("\"state\"") {
        let after = &item[pos + 7..];
        if let Some(open) = after.find('{') {
            if let Some(close) = after[open + 1..].find('}') {
                let inner = &after[open + 1..open + 1 + close];
                for pair in inner.split(',') {
                    if let Some((rk, rv)) = pair.split_once(':') {
                        let k = rk.trim().trim_matches('"');
                        let v = rv.trim().trim_matches('"');
                        if !k.is_empty() {
                            map.insert(k.to_string(), v.to_string());
                        }
                    }
                }
            }
        }
    }
    // 2) Support `state.k=v` or `key=val` pairs (excluding metadata keys)
    for part in item.split([';', '|', '\n']) {
        let tr = part.trim();
        if let Some((k, v)) = tr.split_once('=') {
            let kt = k.trim();
            let vt = v.trim();
            if let Some(sk) = kt.strip_prefix("state.") {
                if !sk.is_empty() {
                    map.insert(sk.to_string(), vt.to_string());
                }
            } else if !matches!(
                kt,
                "recorded_at" | "effective_at" | "as_of" | "seq" | "resource_id"
            ) && !kt.is_empty()
                && !kt.contains('{')
            {
                map.insert(kt.to_string(), vt.to_string());
            }
        }
    }
    map
}

pub fn snapshot_at(
    resource_id: String,
    items: Vec<String>,
    as_of: String,
    effective: Option<String>,
) -> Result<BitemporalSnapshot, &'static str> {
    if resource_id.trim().is_empty() {
        return Err("resource_id MUST be non-empty");
    }
    let as_of_norm = ensure_aware(as_of);
    if as_of_norm.is_empty() {
        return Err("as_of MUST be a valid ISO-8601 timestamp");
    }
    let eff_norm = match effective {
        Some(e) if !e.trim().is_empty() => ensure_aware(e),
        _ => as_of_norm.clone(),
    };
    if eff_norm.is_empty() {
        return Err("effective MUST be a valid ISO-8601 timestamp");
    }
    if eff_norm > as_of_norm {
        return Err("effective MUST be <= as_of; bitemporal snapshots do not predict");
    }

    let mut scored: Vec<(String, String, i64, BTreeMap<String, String>)> = Vec::new();
    for (idx, item) in items.iter().enumerate() {
        let Some(rec_raw) = extract_field_value(item, "recorded_at") else {
            continue;
        };
        let Some(recorded) = parse_ts(Some(rec_raw)) else {
            continue;
        };
        if recorded > as_of_norm {
            continue;
        }
        let eff_raw = extract_field_value(item, "effective_at").unwrap_or_else(|| recorded.clone());
        let Some(eff_ts) = parse_ts(Some(eff_raw)) else {
            continue;
        };
        if eff_ts > eff_norm {
            continue;
        }
        let seq = extract_field_value(item, "seq")
            .and_then(|s| s.parse::<i64>().ok())
            .unwrap_or((idx + 1) as i64);
        let entries = parse_state_entries(item);
        scored.push((eff_ts, recorded, seq, entries));
    }

    scored.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)).then_with(|| a.2.cmp(&b.2)));

    let mut folded = BTreeMap::new();
    let mut provenance = Vec::with_capacity(scored.len());
    for (_, _, seq, entries) in scored {
        provenance.push(seq);
        for (k, v) in entries {
            folded.insert(k, v);
        }
    }

    Ok(BitemporalSnapshot {
        resource_id,
        as_of: as_of_norm,
        effective: eff_norm,
        state: folded,
        source_seqs: provenance,
    })
}

/// Normalize an ISO-8601 timestamp into UTC-aware canonical form (`YYYY-MM-DDTHH:MM:SSZ`).
#[must_use]
pub fn ensure_aware(dt: String) -> String {
    let tr = dt.trim();
    if tr.len() < 10 {
        return String::new();
    }
    let normalized = tr.replace(' ', "T");
    if normalized.ends_with('Z') || normalized.ends_with("+00:00") || normalized.ends_with("-00:00") {
        normalized
            .strip_suffix("+00:00")
            .or_else(|| normalized.strip_suffix("-00:00"))
            .map_or(normalized.clone(), |p| format!("{p}Z"))
    } else if normalized.len() == 10 {
        format!("{normalized}T00:00:00Z")
    } else if normalized.contains('+') || normalized[10..].contains('-') {
        normalized
    } else {
        format!("{normalized}Z")
    }
}

#[must_use]
pub fn parse_ts(raw: Option<String>) -> Option<String> {
    let text = raw?;
    let aware = ensure_aware(text);
    if aware.len() >= 19 && aware.as_bytes()[4] == b'-' && aware.as_bytes()[7] == b'-' {
        Some(aware)
    } else {
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &[
    "BitemporalAuditSource",
    "BitemporalQueryError",
    "BitemporalSnapshot",
    "snapshot_at",
];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bitemporal_snapshot_blocks_future_records_and_folds_state_in_order() -> Result<(), &'static str> {
        let items = vec![
            String::from("{\"seq\":1,\"recorded_at\":\"2026-10-01T10:00:00Z\",\"effective_at\":\"2026-10-01T09:55:00Z\",\"state\":{\"sku\":\"Standard_D4s_v5\",\"status\":\"running\"}}"),
            String::from("{\"seq\":2,\"recorded_at\":\"2026-10-01T10:05:00Z\",\"effective_at\":\"2026-10-01T10:02:00Z\",\"state\":{\"sku\":\"Standard_D2s_v5\"}}"),
            // Future knowledge record past as_of cutoff MUST be excluded
            String::from("{\"seq\":3,\"recorded_at\":\"2026-10-01T10:20:00Z\",\"effective_at\":\"2026-10-01T10:03:00Z\",\"state\":{\"status\":\"stopped\"}}"),
        ];
        let snap = snapshot_at(
            String::from("/subscriptions/sub-1/rg/vm-1"),
            items,
            String::from("2026-10-01T10:10:00Z"),
            None,
        )?;
        assert_eq!(snap.source_seqs, vec![1, 2]);
        assert_eq!(snap.state.get("sku").map(String::as_str), Some("Standard_D2s_v5"));
        assert_eq!(snap.state.get("status").map(String::as_str), Some("running"));

        // Effective > as_of MUST be rejected (no prediction via bitemporal snapshot)
        let bad = snapshot_at(
            String::from("res-1"),
            Vec::new(),
            String::from("2026-10-01T10:00:00Z"),
            Some(String::from("2026-10-01T10:30:00Z")),
        );
        assert!(bad.is_err());
        Ok(())
    }
}
