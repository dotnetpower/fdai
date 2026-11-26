#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HtmlFormatEncoder {
    pub initialized: bool,
}

impl HtmlFormatEncoder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn encode(&self, mut report: String) -> Vec<u8> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_widget(mut widget: String) -> Vec<String> {
    if widget.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_table(mut data: std::collections::BTreeMap<String, String>) -> Vec<String> {
    let mut out: Vec<String> = vec![String::from("<table>"), String::from("<thead><tr>")];
    out.push(String::from("</tr></thead><tbody>"));
    out.push(String::from("</tbody></table>"));
    out.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["HtmlFormatEncoder"];
