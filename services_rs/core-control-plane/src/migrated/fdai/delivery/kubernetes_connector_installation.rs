use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct GatewayPeer {
    pub namespace: String,
    pub labels: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObserverInstallationInput {
    pub target_ref: String,
    pub method: String,
    pub egress: String,
    pub namespace: String,
    pub name: String,
    pub image: String,
    pub material_secret: String,
    pub material_digest: String,
    pub storage_class: String,
    pub gateway_port: i64,
    pub api_port: i64,
    pub gateway_cidrs: Vec<String>,
    #[allow(clippy::type_complexity)]
    pub gateway_peer: Option<Box<GatewayPeer>>,
    pub api_cidrs: Vec<String>,
    pub dns_cidrs: Vec<String>,
}

impl ObserverInstallationInput {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.egress.as_str(), "private" | "public") { return Err("invalid egress literal"); }
        if !(1_i64..=65535_i64).contains(&self.gateway_port) { return Err("gateway_port out of bounds"); }
        if !(1_i64..=65535_i64).contains(&self.api_port) { return Err("api_port out of bounds"); }
        Ok(())
    }
}

pub const PROPOSAL_ANNOTATION: &str = "fdai.dev/proposal-digest";
impl GatewayPeer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn not_system(mut value: String) -> Result<String, &'static str> {
        if (value.clone()).starts_with("kube-") {
            return Err("an in-cluster gateway cannot live in a system namespace");
        }
        Ok(value.clone())
    }
}

impl ObserverInstallationInput {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn gateway_destination(&self) -> Result<String, &'static str> {
        if ((self.gateway_cidrs.clone()).is_empty()) && (self.gateway_peer.is_none()) {
            return Err("the gateway needs bounded networks or an in-cluster peer");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn namespace(mut value: String) -> Result<String, &'static str> {
        if ((value.clone()) == (String::from("default"))) || (((value.clone()).starts_with("kube-")) || ((value.clone()) == (String::from("fdai-runtime")))) {
            return Err("observer preview requires a dedicated non-system namespace");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn networks(mut values: Vec<String>) -> Result<Vec<String>, &'static str> {
        let mut result: Vec<String> = Vec::<String>::new();
        if ((((result.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((result.clone()).len() as i64)) {
            return Err("observer egress networks must be unique");
        }
        Ok({ let mut _v = result.clone(); _v.sort(); _v })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_installation_material(mut inputs: ObserverInstallationInput, mut directory: String, mut now: String) -> Result<(), &'static str> {
    let paths: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("registration_path"), String::new()), (String::from("tls_ca_path"), String::new()), (String::from("tls_certificate_path"), String::new()), (String::from("tls_key_path"), String::new()), (String::from("spool_directory"), String::new()), (String::from("api_ca_path"), String::new()), (String::from("api_token_path"), String::new())]);
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn render_observer_installation(mut inputs: ObserverInstallationInput, mut proposal: String, mut now: String, mut material_directory: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let _ = validate_installation_material(inputs.clone(), material_directory.clone(), now.clone()).unwrap_or_else(|_| ());
    let labels: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("app.kubernetes.io/name"), String::from("fdai-cluster-observer")), (String::from("app.kubernetes.io/instance"), inputs.name.clone())]);
    let annotation: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from(PROPOSAL_ANNOTATION), String::new()), (String::from("fdai.dev/execution-authority"), String::from("false"))]);
    let groups: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::<String, Vec<String>>::new();
    let security: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("privileged"), String::new()), (String::from("allowPrivilegeEscalation"), String::new()), (String::from("readOnlyRootFilesystem"), String::new()), (String::from("capabilities"), String::new()), (String::from("runAsNonRoot"), String::new()), (String::from("runAsUser"), String::new()), (String::from("runAsGroup"), String::new()), (String::from("seccompProfile"), String::new())]);
    let common: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("image"), inputs.image.clone()), (String::from("imagePullPolicy"), String::from("IfNotPresent")), (String::from("securityContext"), String::new()), (String::from("resources"), String::new())]);
    let pod: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("hostNetwork"), String::new()), (String::from("hostPID"), String::new()), (String::from("hostIPC"), String::new()), (String::from("serviceAccountName"), inputs.name.clone()), (String::from("automountServiceAccountToken"), String::new()), (String::from("restartPolicy"), String::from("Never")), (String::from("terminationGracePeriodSeconds"), String::new()), (String::from("securityContext"), String::new()), (String::from("initContainers"), String::new()), (String::from("containers"), String::new()), (String::from("volumes"), String::new())]);
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("target_ref"), inputs.target_ref.clone()), (String::from("proposal_digest"), String::new()), (String::from("method"), String::new()), (String::from("egress"), String::new()), (String::from("missing"), String::new()), (String::from("recommended"), String::new()), (String::from("inputs_digest"), String::new()), (String::from("material_digest"), inputs.material_digest.clone()), (String::from("manifest_digest"), String::new()), (String::from("recipe_digest"), recipe_digest(String::new())), (String::from("documents"), String::new()), (String::from("execution_authority"), String::new()), (String::from("approval_required"), String::new()), (String::from("installation_ready"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn recipe_digest(mut documents: String) -> String {
    if documents.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main() -> i64 {
    0_i64
}

