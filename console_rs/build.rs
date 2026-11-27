use std::collections::BTreeSet;

const LOCKED_CORE_PANELS: [&str; 3] = ["audit", "dashboard", "settings-general"];

const ALL_PANELS: [&str; 65] = [
    // Overview (7)
    "dashboard",
    "dashboard-v2",
    "operating-outcomes",
    "control-assurance",
    "verticals",
    "cost-governance",
    "llm-cost",
    // Operations (18)
    "live",
    "gpu",
    "incidents",
    "code-security",
    "vulnerability-risk",
    "configuration-baselines",
    "hil-queue",
    "alert-quality",
    "detection-readiness",
    "conversation-delivery",
    "workflow-apps",
    "automation-blueprints",
    "processes",
    "scheduler-runs",
    "background-tasks",
    "scheduled-continuations",
    "provision",
    "onboarding",
    // Agents (6)
    "agents",
    "pantheon",
    "handover",
    "agent-activity",
    "skills",
    "capabilities",
    // Governance (13)
    "rules",
    "trust-routing",
    "ontology",
    "scope",
    "architecture",
    "blast-radius",
    "promotion-gates",
    "workflow-builder",
    "knowledge",
    "github",
    "gitlab",
    "azure-devops",
    "documents",
    // Evidence (6)
    "audit",
    "trace",
    "rca",
    "browser-evidence",
    "conversation-search",
    "reports",
    // Chat (1)
    "command-deck-chat",
    // Labs (6)
    "labs",
    "aks-commerce",
    "assurance-twin",
    "forecast-learning",
    "conversation-assurance",
    "context-selection-comparisons",
    // Settings (8)
    "settings-general",
    "settings-environment",
    "settings-models",
    "settings-runtime",
    "settings-iam",
    "settings-integrations",
    "settings-diagnostics",
    "settings-memory",
];

fn parse_csv(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from)
        .collect()
}

fn fail_build(msg: &str) -> ! {
    eprintln!("error: {msg}");
    std::process::exit(1);
}

fn main() {
    println!("cargo:rerun-if-env-changed=FDAI_STENCIL_ENABLED_PANELS");
    println!("cargo:rerun-if-env-changed=FDAI_STENCIL_DISABLED_PANELS");
    println!("cargo:rerun-if-env-changed=FDAI_STENCIL_ID");
    println!("cargo:rerun-if-env-changed=FDAI_STENCIL_ENFORCE_INACTIVE_MENUS");

    let valid: BTreeSet<&str> = ALL_PANELS.iter().copied().collect();
    let mut active = false;

    if let Ok(raw_enabled) = std::env::var("FDAI_STENCIL_ENABLED_PANELS") {
        let trimmed = raw_enabled.trim();
        if !trimmed.is_empty() {
            active = true;
            let items = parse_csv(trimmed);
            if items.is_empty() {
                fail_build("FDAI_STENCIL_ENABLED_PANELS cannot be empty when set");
            }
            let mut chosen = BTreeSet::new();
            for item in &items {
                if !valid.contains(item.as_str()) {
                    fail_build(&format!(
                        "Unknown panel ID in FDAI_STENCIL_ENABLED_PANELS: '{item}'"
                    ));
                }
                chosen.insert(item.as_str());
            }
            for locked in LOCKED_CORE_PANELS {
                if !chosen.contains(locked) {
                    fail_build(&format!(
                        "Locked core panel '{locked}' must be included in FDAI_STENCIL_ENABLED_PANELS"
                    ));
                }
            }
        }
    }

    if let Ok(raw_disabled) = std::env::var("FDAI_STENCIL_DISABLED_PANELS") {
        let trimmed = raw_disabled.trim();
        if !trimmed.is_empty() {
            active = true;
            for item in parse_csv(trimmed) {
                if !valid.contains(item.as_str()) {
                    fail_build(&format!(
                        "Unknown panel ID in FDAI_STENCIL_DISABLED_PANELS: '{item}'"
                    ));
                }
                if LOCKED_CORE_PANELS.contains(&item.as_str()) {
                    fail_build(&format!(
                        "Locked core panel '{item}' cannot be listed in FDAI_STENCIL_DISABLED_PANELS"
                    ));
                }
            }
        }
    }

    if let Ok(raw_enforce) = std::env::var("FDAI_STENCIL_ENFORCE_INACTIVE_MENUS") {
        let token = raw_enforce.trim().to_ascii_lowercase();
        if !token.is_empty() {
            match token.as_str() {
                "1" | "true" | "yes" | "on" => {}
                "0" | "false" | "no" | "off" => {
                    if active {
                        fail_build(
                            "FDAI_STENCIL_ENFORCE_INACTIVE_MENUS cannot disable fail-closed enforcement when a Stencil is active",
                        );
                    }
                }
                _ => fail_build(&format!(
                    "Invalid FDAI_STENCIL_ENFORCE_INACTIVE_MENUS token: '{raw_enforce}'"
                )),
            }
        }
    }
}
