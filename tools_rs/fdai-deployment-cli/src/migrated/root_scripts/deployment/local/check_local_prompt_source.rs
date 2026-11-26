pub const PROMPT_ROOT: &str = "rule-catalog/prompts/";
pub const ALLOW_ENV: &str = "FDAI_LOCAL_ALLOW_DIRTY_PROMPTS";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn dirty_prompt_paths(mut repo_root: String) -> Vec<String> {
    let changed: Vec<String> = git_paths(repo_root.clone(), vec![String::from("diff"), String::from("--name-only"), String::from("HEAD"), String::from("--"), String::from(PROMPT_ROOT)]);
    let untracked: Vec<String> = git_paths(repo_root.clone(), vec![String::from("ls-files"), String::from("--others"), String::from("--exclude-standard"), String::from("--"), String::from(PROMPT_ROOT)]);
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn git_paths(mut repo_root: String, mut args: Vec<String>) -> Vec<String> {
    if repo_root.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    let dirty: Vec<String> = dirty_prompt_paths(String::new());
    if (dirty.clone()).is_empty() {
        return 0_i64;
    }
    1_i64
}

