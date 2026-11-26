#[derive(Clone, Debug, Default, PartialEq)]
pub struct ToolSchema {
    pub verb: String,
    pub tool_name: String,
    pub argument_hint: String,
    pub summary: String,
    pub rbac_floor: String,
    pub side_effect_class: String,
}

pub trait Narrator {
    fn translate(&self, utterance: String, tools: Vec<ToolSchema>, principal_role: String) -> String;
}

pub trait ContextualNarrator {
    fn translate_with_context(&self, utterance: String, tools: Vec<ToolSchema>, prior_turns: Vec<String>, principal_role: String) -> String;
}

pub trait ClarificationNarrator {
    fn clarify(&self, utterance: String, tools: Vec<ToolSchema>, prior_turns: Vec<String>, principal_role: String) -> String;
}

pub trait ReadPlanNarrator {
    fn propose_read_plan(&self, utterance: String, tools: Vec<ToolSchema>, prior_turns: Vec<String>, principal_role: String) -> String;
}

pub trait GroundedAnswerNarrator {
    fn render_answer(&self, utterance: String, tool: ToolSchema, result: String, answer_plan: String, prior_turns: Vec<String>, principal_role: String) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_tool_schemas() -> Vec<ToolSchema> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn format_prompt_tool_list(mut tools: Vec<ToolSchema>, mut principal_role: String) -> String {
    let order: std::collections::BTreeMap<String, i64> = std::collections::BTreeMap::from([(String::from("reader"), 0_i64), (String::from("contributor"), 1_i64), (String::from("approver"), 2_i64), (String::from("owner"), 3_i64), (String::from("break_glass"), 4_i64)]);
    let principal_level: i64 = (order.clone()).get((principal_role.to_lowercase()).as_str()).cloned().unwrap_or_else(|| 0_i64);
    let mut lines: Vec<String> = Vec::<String>::new();
    for schema in tools.clone() {
        let floor_level: i64 = (order.clone()).get(((schema.rbac_floor.clone()).to_lowercase()).as_str()).cloned().unwrap_or_else(|| 0_i64);
        if (floor_level) > (principal_level) {
            continue;
        }
        let arg: String = if !(schema.argument_hint.clone()).is_empty() { format!(" {}", schema.argument_hint.clone()) } else { String::from("") };
        lines.push(format!("- {}{} -- {}", schema.verb.clone(), arg.clone(), schema.summary.clone()));
    }
    (lines.clone()).join("\n")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ClarificationNarrator", "ContextualNarrator", "GroundedAnswerNarrator", "Narrator", "ReadPlanNarrator", "ToolSchema", "default_tool_schemas", "format_prompt_tool_list"];
