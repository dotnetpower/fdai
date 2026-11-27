//! Build-time and runtime Stencil menu enforcement for FDAI Console v4 (`fdai-console-v4`).
//!
//! Honors `FDAI_STENCIL_ENABLED_PANELS`, `FDAI_STENCIL_DISABLED_PANELS`, `FDAI_STENCIL_ID`,
//! and `FDAI_STENCIL_ENFORCE_INACTIVE_MENUS` from both compile-time (`option_env!`, tracked via
//! `build.rs`) and runtime (`std::env::var`), with fail-closed intersection semantics:
//! panels excluded at build time can never be re-enabled at runtime.

use crate::domains;
use serde_json::{json, Value};
use std::collections::BTreeSet;

pub const LOCKED_CORE_PANELS: [&str; 3] = ["audit", "dashboard", "settings-general"];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StencilPolicy {
    pub stencil_id: Option<String>,
    pub active: bool,
    pub enforcement_mode: &'static str,
    pub source: &'static str,
    pub enabled_panels: BTreeSet<String>,
    pub disabled_panels: BTreeSet<String>,
}

fn parse_csv_tokens(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from)
        .collect()
}

fn validate_panel_list(
    raw: &str,
    var_name: &str,
    valid: &BTreeSet<&str>,
) -> Result<BTreeSet<String>, String> {
    let tokens = parse_csv_tokens(raw);
    if tokens.is_empty() {
        return Err(format!("{var_name} contains no valid panel identifiers"));
    }
    let mut set = BTreeSet::new();
    for tok in tokens {
        if !valid.contains(tok.as_str()) {
            return Err(format!("Unknown panel identifier '{tok}' in {var_name}"));
        }
        set.insert(tok);
    }
    Ok(set)
}

fn validate_enforce_token(raw: Option<&str>, active: bool) -> Result<(), String> {
    let Some(val) = raw.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(());
    };
    match val.to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(()),
        "0" | "false" | "no" | "off" => {
            if active {
                Err(String::from(
                    "FDAI_STENCIL_ENFORCE_INACTIVE_MENUS cannot disable fail-closed enforcement while a Stencil is active",
                ))
            } else {
                Ok(())
            }
        }
        _ => Err(format!(
            "Invalid FDAI_STENCIL_ENFORCE_INACTIVE_MENUS boolean token: '{val}'"
        )),
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct StencilLayerInput<'a> {
    pub enabled: Option<&'a str>,
    pub disabled: Option<&'a str>,
    pub stencil_id: Option<&'a str>,
    pub enforce: Option<&'a str>,
}

impl StencilPolicy {
    /// Returns an unscoped policy with all 65 Console v4 panels enabled.
    #[must_use]
    pub fn unscoped() -> Self {
        let enabled_panels: BTreeSet<String> = domains::all_panel_ids()
            .into_iter()
            .map(String::from)
            .collect();
        Self {
            stencil_id: None,
            active: false,
            enforcement_mode: "unscoped",
            source: "unscoped",
            enabled_panels,
            disabled_panels: BTreeSet::new(),
        }
    }

    /// Builds a `StencilPolicy` from explicit compile-time and runtime layers (fail-closed).
    pub fn from_layers(
        compile: StencilLayerInput<'_>,
        runtime: StencilLayerInput<'_>,
    ) -> Result<Self, String> {
        let all_ids = domains::all_panel_ids();
        let valid: BTreeSet<&str> = all_ids.iter().copied().collect();
        let mut enabled: BTreeSet<String> = all_ids.iter().map(|s| String::from(*s)).collect();
        let mut compile_active = false;
        let mut runtime_active = false;

        if let Some(raw) = compile.enabled.map(str::trim).filter(|s| !s.is_empty()) {
            compile_active = true;
            let chosen = validate_panel_list(raw, "FDAI_STENCIL_ENABLED_PANELS (compile)", &valid)?;
            enabled = enabled.intersection(&chosen).cloned().collect();
        }
        if let Some(raw) = compile.disabled.map(str::trim).filter(|s| !s.is_empty()) {
            compile_active = true;
            let blocked =
                validate_panel_list(raw, "FDAI_STENCIL_DISABLED_PANELS (compile)", &valid)?;
            for locked in LOCKED_CORE_PANELS {
                if blocked.contains(locked) {
                    return Err(format!(
                        "Locked core panel '{locked}' cannot be disabled in FDAI_STENCIL_DISABLED_PANELS (compile)"
                    ));
                }
            }
            for item in blocked {
                enabled.remove(&item);
            }
        }

        if let Some(raw) = runtime.enabled.map(str::trim).filter(|s| !s.is_empty()) {
            runtime_active = true;
            let chosen = validate_panel_list(raw, "FDAI_STENCIL_ENABLED_PANELS", &valid)?;
            // Intersection preserves build-time exclusion: runtime cannot re-enable compiled-out panels.
            enabled = enabled.intersection(&chosen).cloned().collect();
        }
        if let Some(raw) = runtime.disabled.map(str::trim).filter(|s| !s.is_empty()) {
            runtime_active = true;
            let blocked = validate_panel_list(raw, "FDAI_STENCIL_DISABLED_PANELS", &valid)?;
            for locked in LOCKED_CORE_PANELS {
                if blocked.contains(locked) {
                    return Err(format!(
                        "Locked core panel '{locked}' cannot be disabled in FDAI_STENCIL_DISABLED_PANELS"
                    ));
                }
            }
            for item in blocked {
                enabled.remove(&item);
            }
        }

        let active = compile_active || runtime_active;
        validate_enforce_token(compile.enforce, active)?;
        validate_enforce_token(runtime.enforce, active)?;

        if active {
            for locked in LOCKED_CORE_PANELS {
                if !enabled.contains(locked) {
                    return Err(format!(
                        "Locked core panel '{locked}' must remain enabled in active Stencil policy"
                    ));
                }
            }
        }

        let disabled: BTreeSet<String> = all_ids
            .iter()
            .filter(|id| !enabled.contains(**id))
            .map(|id| String::from(*id))
            .collect();

        let stencil_id = runtime
            .stencil_id
            .or(compile.stencil_id)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from);

        let source = match (compile_active, runtime_active) {
            (true, true) => "compile-and-runtime",
            (true, false) => "compile-time",
            (false, true) => "runtime-env",
            (false, false) => "unscoped",
        };

        Ok(Self {
            stencil_id,
            active,
            enforcement_mode: if active { "fail-closed" } else { "unscoped" },
            source,
            enabled_panels: enabled,
            disabled_panels: disabled,
        })
    }

    /// Loads compile-time (`option_env!`) + runtime (`std::env::var`) Stencil configuration.
    pub fn from_current_env_checked() -> Result<Self, String> {
        let rt_enabled = std::env::var("FDAI_STENCIL_ENABLED_PANELS").ok();
        let rt_disabled = std::env::var("FDAI_STENCIL_DISABLED_PANELS").ok();
        let rt_id = std::env::var("FDAI_STENCIL_ID").ok();
        let rt_enforce = std::env::var("FDAI_STENCIL_ENFORCE_INACTIVE_MENUS").ok();
        Self::from_layers(
            StencilLayerInput {
                enabled: option_env!("FDAI_STENCIL_ENABLED_PANELS"),
                disabled: option_env!("FDAI_STENCIL_DISABLED_PANELS"),
                stencil_id: option_env!("FDAI_STENCIL_ID"),
                enforce: option_env!("FDAI_STENCIL_ENFORCE_INACTIVE_MENUS"),
            },
            StencilLayerInput {
                enabled: rt_enabled.as_deref(),
                disabled: rt_disabled.as_deref(),
                stencil_id: rt_id.as_deref(),
                enforce: rt_enforce.as_deref(),
            },
        )
    }

    /// Loads Stencil configuration for library callers; fails closed to locked core panels on malformed runtime env.
    #[must_use]
    pub fn from_current_env_fail_closed() -> Self {
        Self::from_current_env_checked().unwrap_or_else(|_| {
            let locked: BTreeSet<String> = LOCKED_CORE_PANELS
                .iter()
                .map(|s| String::from(*s))
                .collect();
            let disabled: BTreeSet<String> = domains::all_panel_ids()
                .into_iter()
                .filter(|id| !locked.contains(*id))
                .map(String::from)
                .collect();
            Self {
                stencil_id: Some(String::from("fail-closed-invalid-config")),
                active: true,
                enforcement_mode: "fail-closed",
                source: "fail-closed-fallback",
                enabled_panels: locked,
                disabled_panels: disabled,
            }
        })
    }

    #[must_use]
    pub fn is_panel_enabled(&self, panel_id: &str) -> bool {
        !self.active || self.enabled_panels.contains(panel_id)
    }

    #[must_use]
    pub fn enabled_panels_for_domain(&self, domain_id: &str) -> Vec<&'static str> {
        domain_panels(domain_id)
            .iter()
            .copied()
            .filter(|pid| self.is_panel_enabled(pid))
            .collect()
    }

    #[must_use]
    pub fn is_domain_enabled(&self, domain_id: &str) -> bool {
        !self.active || !self.enabled_panels_for_domain(domain_id).is_empty()
    }

    #[must_use]
    pub fn first_enabled_panel_for_domain(&self, domain_id: &str) -> Option<&'static str> {
        self.enabled_panels_for_domain(domain_id).into_iter().next()
    }

    #[must_use]
    pub fn to_bootstrap_json(&self) -> Value {
        let enabled: Vec<&str> = self.enabled_panels.iter().map(String::as_str).collect();
        let disabled: Vec<&str> = self.disabled_panels.iter().map(String::as_str).collect();
        json!({
            "active": self.active,
            "stencilId": self.stencil_id,
            "enforcementMode": self.enforcement_mode,
            "source": self.source,
            "enabledPanels": enabled,
            "disabledPanels": disabled,
            "enabledCount": self.enabled_panels.len(),
            "totalPanels": self.enabled_panels.len() + self.disabled_panels.len(),
        })
    }

    #[must_use]
    pub fn filtered_domain_manifest(&self) -> Vec<Value> {
        [
            ("overview", "/overview"),
            ("operations", "/operations"),
            ("agents", "/agents"),
            ("governance", "/governance"),
            ("evidence", "/evidence"),
            ("settings", "/settings"),
            ("labs", "/labs"),
            ("chat", "/chat"),
        ]
        .into_iter()
        .filter_map(|(id, route)| {
            let panels = self.enabled_panels_for_domain(id);
            if self.active && panels.is_empty() {
                None
            } else {
                Some(json!({ "id": id, "route": route, "panels": panels }))
            }
        })
        .collect()
    }
}

#[must_use]
pub fn domain_panels(domain_id: &str) -> &'static [&'static str] {
    match domain_id {
        "overview" => domains::overview::panel_ids(),
        "operations" => domains::operations::panel_ids(),
        "agents" => domains::agents::panel_ids(),
        "governance" => domains::governance::panel_ids(),
        "evidence" => domains::evidence::panel_ids(),
        "settings" => domains::settings::panel_ids(),
        "labs" => domains::labs::panel_ids(),
        "chat" => domains::chat::panel_ids(),
        _ => &[],
    }
}

#[must_use]
pub fn default_panel_for_domain(domain_id: &str) -> Option<&'static str> {
    match domain_id {
        "overview" => Some("dashboard"),
        "operations" => Some("live"),
        "agents" => Some("agents"),
        "governance" => Some("rules"),
        "evidence" => Some("audit"),
        "settings" => Some("settings-general"),
        "labs" => Some("labs"),
        "chat" => Some("command-deck-chat"),
        _ => None,
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum RouteStencilTarget {
    /// Domain root page (e.g. `/operations`, `/labs`).
    DomainRoot { domain: &'static str, default_panel: &'static str },
    /// Specific Console panel page (canonical or legacy flat alias).
    PanelPage { panel_id: String },
    /// Domain/panel JSON API endpoint under `/api/v4/...`.
    ApiEndpoint { domain: &'static str, panel_id: Option<&'static str> },
}

/// Maps an HTTP request path to its governing Stencil target, if any.
#[must_use]
pub fn resolve_route_target(raw_path: &str) -> Option<RouteStencilTarget> {
    let clean = raw_path.trim_end_matches('/');
    let path = if clean.is_empty() { "/" } else { clean };

    match path {
        "/" | "/overview" => {
            return Some(RouteStencilTarget::DomainRoot {
                domain: "overview",
                default_panel: "dashboard",
            });
        }
        "/operations" => {
            return Some(RouteStencilTarget::DomainRoot {
                domain: "operations",
                default_panel: "live",
            });
        }
        "/agents" => {
            return Some(RouteStencilTarget::DomainRoot {
                domain: "agents",
                default_panel: "agents",
            });
        }
        "/governance" => {
            return Some(RouteStencilTarget::DomainRoot {
                domain: "governance",
                default_panel: "rules",
            });
        }
        "/evidence" => {
            return Some(RouteStencilTarget::DomainRoot {
                domain: "evidence",
                default_panel: "audit",
            });
        }
        "/settings" => {
            return Some(RouteStencilTarget::DomainRoot {
                domain: "settings",
                default_panel: "settings-general",
            });
        }
        "/labs" => {
            return Some(RouteStencilTarget::DomainRoot {
                domain: "labs",
                default_panel: "labs",
            });
        }
        "/chat" => {
            return Some(RouteStencilTarget::PanelPage {
                panel_id: String::from("command-deck-chat"),
            });
        }
        _ => {}
    }

    if let Some(rest) = path.strip_prefix("/api/v4/") {
        return resolve_api_target(rest);
    }

    if let Some(suffix) = path.strip_prefix("/settings/") {
        let candidate = format!("settings-{suffix}");
        if domains::settings::panel_ids().contains(&candidate.as_str()) {
            return Some(RouteStencilTarget::PanelPage { panel_id: candidate });
        }
        return None;
    }

    if let Some(sub) = path.strip_prefix("/labs/") {
        if domains::labs::panel_ids().contains(&sub) {
            return Some(RouteStencilTarget::PanelPage {
                panel_id: sub.to_string(),
            });
        }
        return None;
    }

    for (prefix, ids) in [
        ("/overview/", domains::overview::panel_ids()),
        ("/operations/", domains::operations::panel_ids()),
        ("/agents/", domains::agents::panel_ids()),
        ("/governance/", domains::governance::panel_ids()),
        ("/evidence/", domains::evidence::panel_ids()),
    ] {
        if let Some(sub) = path.strip_prefix(prefix) {
            if ids.contains(&sub) {
                return Some(RouteStencilTarget::PanelPage {
                    panel_id: sub.to_string(),
                });
            }
            return None;
        }
    }

    // Legacy flat panel alias (e.g. `/gpu`, `/hil-queue`, `/settings-models`)
    if let Some(flat) = path.strip_prefix('/') {
        if !flat.contains('/') && domains::all_panel_ids().contains(&flat) {
            return Some(RouteStencilTarget::PanelPage {
                panel_id: flat.to_string(),
            });
        }
    }

    None
}

fn resolve_api_target(rest: &str) -> Option<RouteStencilTarget> {
    let mut parts = rest.split('/').filter(|s| !s.is_empty());
    let domain = parts.next()?;
    let seg = parts.next().unwrap_or("");
    match domain {
        "overview" => {
            let panel = match seg {
                "dashboard" => Some("dashboard"),
                "resources" => Some("dashboard-v2"),
                "outcomes" => Some("operating-outcomes"),
                "control-assurance" => Some("control-assurance"),
                "verticals" => Some("verticals"),
                "cost-governance" => Some("cost-governance"),
                "llm-cost" => Some("llm-cost"),
                _ => None,
            };
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "overview",
                panel_id: panel,
            })
        }
        "operations" => {
            let panel = match seg {
                "live" => Some("live"),
                "gpu" => Some("gpu"),
                "incidents" => Some("incidents"),
                "security" | "code-security" => Some("code-security"),
                "vulnerability-risk" => Some("vulnerability-risk"),
                "baselines" | "configuration-baselines" => Some("configuration-baselines"),
                "hil-queue" => Some("hil-queue"),
                "alert-quality" => Some("alert-quality"),
                "detection-readiness" => Some("detection-readiness"),
                "conversation-delivery" => Some("conversation-delivery"),
                "workflow-apps" | "automation" => Some("workflow-apps"),
                "automation-blueprints" => Some("automation-blueprints"),
                "processes" => Some("processes"),
                "scheduler-runs" => Some("scheduler-runs"),
                "background-tasks" => Some("background-tasks"),
                "scheduled-continuations" => Some("scheduled-continuations"),
                "provision" => Some("provision"),
                "onboarding" => Some("onboarding"),
                _ => None,
            };
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "operations",
                panel_id: panel,
            })
        }
        "agents" => {
            let panel = match seg {
                "roster" | "fleet" => Some("agents"),
                "pantheon" => Some("pantheon"),
                "handover" => Some("handover"),
                "activity" | "agent-activity" => Some("agent-activity"),
                "skills" => Some("skills"),
                "capabilities" => Some("capabilities"),
                _ => None,
            };
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "agents",
                panel_id: panel,
            })
        }
        "governance" => {
            let panel = match seg {
                "rules" => Some("rules"),
                "trust-routing" => Some("trust-routing"),
                "ontology" => Some("ontology"),
                "scope" => Some("scope"),
                "architecture" => Some("architecture"),
                "blast-radius" => Some("blast-radius"),
                "promotion-gates" => Some("promotion-gates"),
                "workflows" | "workflow-builder" => Some("workflow-builder"),
                "knowledge" => Some("knowledge"),
                "github" => Some("github"),
                "gitlab" => Some("gitlab"),
                "azure-devops" => Some("azure-devops"),
                "documents" => Some("documents"),
                _ => None,
            };
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "governance",
                panel_id: panel,
            })
        }
        "evidence" => {
            let panel = match seg {
                "audit" => Some("audit"),
                "trace" => Some("trace"),
                "rca" => Some("rca"),
                "browser-evidence" => Some("browser-evidence"),
                "conversations" | "conversation-search" => Some("conversation-search"),
                "reports" => Some("reports"),
                _ => None,
            };
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "evidence",
                panel_id: panel,
            })
        }
        "labs" => {
            let panel = match seg {
                "aks-commerce" => Some("aks-commerce"),
                "assurance-twin" => Some("assurance-twin"),
                "forecast-learning" => Some("forecast-learning"),
                "conversation-assurance" => Some("conversation-assurance"),
                "context-selection-comparisons" => Some("context-selection-comparisons"),
                _ => None,
            };
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "labs",
                panel_id: panel,
            })
        }
        "settings" => {
            let panel = match seg {
                "general" => Some("settings-general"),
                "environment" => Some("settings-environment"),
                "models" => Some("settings-models"),
                "runtime" => Some("settings-runtime"),
                "iam" => Some("settings-iam"),
                "integrations" => Some("settings-integrations"),
                "diagnostics" => Some("settings-diagnostics"),
                "memory" => Some("settings-memory"),
                _ => None,
            };
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "settings",
                panel_id: panel,
            })
        }
        "chat" => Some(RouteStencilTarget::ApiEndpoint {
            domain: "chat",
            panel_id: Some("command-deck-chat"),
        }),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unscoped_enables_all_65_panels() {
        let p = StencilPolicy::unscoped();
        assert!(!p.active);
        assert_eq!(p.enabled_panels.len(), 65);
        assert!(p.disabled_panels.is_empty());
        assert!(p.is_panel_enabled("labs"));
    }

    #[test]
    fn compile_time_exclusions_cannot_be_re_enabled_at_runtime() -> Result<(), String> {
        let p = StencilPolicy::from_layers(
            StencilLayerInput {
                enabled: Some("audit,dashboard,live,settings-general"),
                stencil_id: Some("lite-observe-alert"),
                enforce: Some("1"),
                ..StencilLayerInput::default()
            },
            StencilLayerInput {
                enabled: Some("audit,dashboard,live,hil-queue,labs,settings-general"),
                enforce: Some("1"),
                ..StencilLayerInput::default()
            },
        )?;
        assert!(p.active);
        assert_eq!(p.source, "compile-and-runtime");
        assert!(p.is_panel_enabled("dashboard"));
        assert!(p.is_panel_enabled("live"));
        assert!(!p.is_panel_enabled("hil-queue"));
        assert!(!p.is_panel_enabled("labs"));
        assert!(!p.is_domain_enabled("labs"));
        assert_eq!(p.enabled_panels.len(), 4);
        Ok(())
    }

    #[test]
    fn rejects_unknown_panel_missing_locked_core_and_enforce_disable() {
        assert!(StencilPolicy::from_layers(
            StencilLayerInput {
                enabled: Some("audit,dashboard,settings-general,nonexistent"),
                ..StencilLayerInput::default()
            },
            StencilLayerInput::default(),
        )
        .is_err());

        assert!(StencilPolicy::from_layers(
            StencilLayerInput {
                enabled: Some("dashboard,live"),
                ..StencilLayerInput::default()
            },
            StencilLayerInput::default(),
        )
        .is_err());

        assert!(StencilPolicy::from_layers(
            StencilLayerInput {
                disabled: Some("audit"),
                ..StencilLayerInput::default()
            },
            StencilLayerInput::default(),
        )
        .is_err());

        assert!(StencilPolicy::from_layers(
            StencilLayerInput {
                enabled: Some("audit,dashboard,settings-general"),
                enforce: Some("false"),
                ..StencilLayerInput::default()
            },
            StencilLayerInput::default(),
        )
        .is_err());
    }

    #[test]
    fn route_resolution_maps_pages_and_apis() {
        assert_eq!(
            resolve_route_target("/operations/hil-queue"),
            Some(RouteStencilTarget::PanelPage {
                panel_id: String::from("hil-queue")
            })
        );
        assert_eq!(
            resolve_route_target("/settings/models"),
            Some(RouteStencilTarget::PanelPage {
                panel_id: String::from("settings-models")
            })
        );
        assert_eq!(
            resolve_route_target("/labs/aks-commerce"),
            Some(RouteStencilTarget::PanelPage {
                panel_id: String::from("aks-commerce")
            })
        );
        assert_eq!(
            resolve_route_target("/api/v4/operations/hil-queue"),
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "operations",
                panel_id: Some("hil-queue")
            })
        );
        assert_eq!(
            resolve_route_target("/api/v4/chat/send"),
            Some(RouteStencilTarget::ApiEndpoint {
                domain: "chat",
                panel_id: Some("command-deck-chat")
            })
        );
    }
}
