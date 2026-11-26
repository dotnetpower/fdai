use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ArgFilterOperator {
    #[default]
    Equals,
    In,
    ContainsCi,
    StartswithCi,
    NotEmpty,
}

impl ArgFilterOperator {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Equals => "equals",
            Self::In => "in",
            Self::ContainsCi => "contains_ci",
            Self::StartswithCi => "startswith_ci",
            Self::NotEmpty => "not_empty",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArgWherePredicate {
    pub column: String,
    pub operator: ArgFilterOperator,
    pub values: Vec<String>,
}

impl ArgWherePredicate {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.column.trim().is_empty() { return Err("column must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArgCatalogQueryRequest {
    pub table_name: String,
    pub subscription_ids: Vec<String>,
    pub resource_types: Vec<String>,
    pub resource_groups: Vec<String>,
    pub where_predicates: Vec<ArgWherePredicate>,
    pub project_columns: Vec<String>,
    pub order_by_column: String,
    pub order_descending: bool,
    pub limit: i64,
}

impl ArgCatalogQueryRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.table_name.trim().is_empty() { return Err("table_name must be non-empty"); }
        if self.order_by_column.trim().is_empty() { return Err("order_by_column must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ArgCatalogQueryResult {
    pub table_name: String,
    pub owner_agent: String,
    pub domain: String,
    pub compiled_kql: String,
    pub query_digest: String,
    #[allow(clippy::type_complexity)]
    pub rows: Vec<BTreeMap<String, String>>,
    pub truncated: bool,
    pub observed_at: String,
    pub execution_authority: bool,
}

pub const ARG_API_VERSION: &str = "2022-10-01";
pub const ARM_AUDIENCE: &str = "https://management.azure.com/.default";
pub const SAFE_RG_RE: &str = "^[A-Za-z0-9._()-]{1,90}$";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ArgCatalogQueryEngine {
    pub initialized: bool,
}

impl ArgCatalogQueryEngine {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut request: ArgCatalogQueryRequest) -> Result<ArgCatalogQueryResult, &'static str> {
        let kql: String = compile_arg_catalog_query(request.clone(), None).unwrap_or_else(|_| String::new());
        let payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("subscriptions"), String::new()), (String::from("query"), kql.clone()), (String::from("options"), String::new())]);
        Ok(ArgCatalogQueryResult { compiled_kql: kql.clone(), ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn escape_kql_literal(mut value: String) -> Result<String, &'static str> {
    let escaped: String = ((value.clone()).replace("\\", "\\\\")).replace("'", "\\'");
    Ok(format!("'{}'", escaped.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn validate_column_or_prop(mut column: String, mut allowed_columns: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
    let clean: String = column.trim().to_string();
    if (allowed_columns.clone()).contains(clean.as_str()) {
        return Ok(clean.clone());
    }
    Err("Column columnr is not permitted for this ARG table")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn compile_arg_catalog_query(mut request: ArgCatalogQueryRequest, mut catalog: Option<String>) -> Result<String, &'static str> {
    if !(request.resource_types.clone()).is_empty() {
        let mut cleaned_types: Vec<String> = Vec::<String>::new();
        for rt in request.resource_types.clone() {
            let clean_rt: String = (rt.trim().to_string()).to_lowercase();
            if ((clean_rt.clone()).is_empty()) || (!((clean_rt.clone()).contains("/"))) {
                return Err("Invalid ARM resource_type filter: rtr");
            }
            cleaned_types.push(escape_kql_literal(clean_rt.clone()).unwrap_or_else(|_| String::new()));
        }
    }
    for pred in request.where_predicates.clone() {
        let expr: String = validate_column_or_prop(pred.column.clone(), std::collections::BTreeSet::new()).unwrap_or_else(|_| String::new());
    }
    let order_col: String = (request.order_by_column.clone()).trim().to_string();
    let mut validated_projects: Vec<String> = Vec::<String>::new();
    if !((validated_projects.clone()).contains(&(order_col.clone()))) {
        validated_projects.push(order_col.clone());
    }
    let direction: String = if request.order_descending { String::from("desc") } else { String::from("asc") };
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ArgCatalogQueryEngine", "ArgCatalogQueryRequest", "ArgCatalogQueryResult", "ArgFilterOperator", "ArgWherePredicate", "compile_arg_catalog_query"];
