#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HostmapBuilder {
    pub initialized: bool,
}

impl HostmapBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut tiles: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        std::collections::BTreeMap::from([(String::from("tiles"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TopologyMapBuilder {
    pub initialized: bool,
}

impl TopologyMapBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut nodes: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
        let mut edges: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        std::collections::BTreeMap::from([(String::from("nodes"), String::new()), (String::from("edges"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GeomapBuilder {
    pub initialized: bool,
}

impl GeomapBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut points: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        let mut areas: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        std::collections::BTreeMap::from([(String::from("points"), String::new()), (String::from("areas"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["GeomapBuilder", "HostmapBuilder", "TopologyMapBuilder"];
