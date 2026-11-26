#[derive(Clone, Debug, Default, PartialEq)]
pub struct ViewAppliesTo {
    pub workflow_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ViewRegion {
    pub id: String,
    pub report_ref: String,
    pub column_span: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ViewSpec {
    pub id: String,
    pub version: String,
    pub name: String,
    pub description: String,
    pub route: String,
    pub applies_to: Box<ViewAppliesTo>,
    pub regions: Vec<ViewRegion>,
}

pub const PUBLIC_EXPORTS: &[&str] = &["ViewAppliesTo", "ViewRegion", "ViewSpec"];
