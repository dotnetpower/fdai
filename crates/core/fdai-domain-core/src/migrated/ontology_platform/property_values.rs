pub const MAX_VALUES: i64 = 512;
pub const MAX_GROUPS: i64 = 192;
pub const MAX_TERMS: i64 = 64;
pub const MAX_TEXT: i64 = 128;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PropertyValueGroup {
    pub id: String,
    pub values: Vec<String>,
    pub terms: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PropertyValueDomain {
    pub object_type: String,
    pub property_name: String,
    pub values: Vec<String>,
    pub groups: Vec<PropertyValueGroup>,
    pub lifecycle_state: bool,
}

impl PropertyValueDomain {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn projection(&self) -> std::collections::BTreeMap<String, String> {
        let mut facet: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("values"), String::new())]);
        facet.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn property_value_index(mut domains: Vec<PropertyValueDomain>) -> Result<std::collections::BTreeMap<String, PropertyValueDomain>, &'static str> {
    let mut index: std::collections::BTreeMap<String, PropertyValueDomain> = std::collections::BTreeMap::<String, PropertyValueDomain>::new();
    Ok(index.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn declared_property_values(mut descriptor_property: String) -> Option<std::collections::BTreeSet<String>> {
    if !(false) {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_identifier(mut value: String, mut label: String) -> Result<(), &'static str> {
    if ((value.trim().to_string()).is_empty()) || (((value.clone()) != (value.trim().to_string())) || ((((value.clone()).len() as i64)) > (MAX_TEXT))) {
        return Err("label MUST be non-empty and bounded");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_sorted_unique(mut values: Vec<String>, mut label: String, mut maximum: i64) -> Result<(), &'static str> {
    if (((values.clone()).len() as i64)) > (maximum) {
        return Err("label MUST contain at most maximum entries");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["PropertyValueDomain", "PropertyValueGroup", "declared_property_values", "property_value_index"];
