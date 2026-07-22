# Bootstrap (ops / hub) layer

On a policy-locked tenant that forces **every data service to private**
(`publicNetworkAccess: Disabled` on Key Vault *and* storage), a laptop cannot
write Key Vault secrets or reach a terraform remote-state backend. The deploy
must run from **inside the VNet**. This layer stands up the durable hub that
makes that possible, and it survives app rebuilds.

## What it creates

| Resource | Why |
|----------|-----|
| Ops resource group `rg-<workload>-ops-<region_short>` | Separate from the app RG so it outlives app teardowns. |
| Ops (hub) VNet + `snet-runner` + `snet-pe` | Stable network the runner lives in. |
| State storage account (private) + `tfstate` and `deployment-plans` containers | Terraform remote backend plus protected plan artifacts the runner reaches over a private endpoint. |
| Blob private endpoint + `privatelink.blob.core.windows.net` | Private resolution of the state account from the ops VNet. |
| NAT gateway + static public IP on `snet-runner` (`nat.tf`) | Explicit, durable outbound egress. The subnet originally relied on Azure "default outbound access", which is being retired: after a VM deallocate/start cycle the runner lost all outbound internet (GitHub + ARM + AAD all timed out) while the private state endpoint stayed reachable. A NAT gateway restores egress through one static IP while the VM keeps **no** public IP (no inbound exposure), and it survives deallocate/start cycles. |
| Runner VM (no public IP) + system-assigned MI | The only host with line-of-sight to the app's private endpoints. |
| Role assignments | Runner MI -> Contributor + User Access Administrator on the app RG, Network Contributor on the ops RG, Storage Blob Data Contributor on state, and EventGrid Contributor on the subscription. |

The app config (`../`) peers its spoke VNet to `ops_vnet_id`, links its
private DNS zones to the ops VNet, and grants `runner_principal_id` **Key Vault
Secrets Officer** on the app vault.

## Usage

```bash
cp bootstrap.tfvars.example bootstrap.tfvars   # fill in, gitignored

# 1. Create the state storage account with `az` (control plane only). A
#    private + key-disabled account cannot complete terraform's data-plane
#    readiness poll from a laptop, so it is created out of band and terraform
#    references it via a data source. Copy the printed name into bootstrap.tfvars
#    (state_storage_account_name).
OPS_RG=rg-fdai-ops-krc REGION=koreacentral ./create-state-account.sh

# 2. Apply the ops layer (VNet, blob PE, runner VM, role assignments).
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply -var-file=bootstrap.tfvars
terraform -chdir=infra/bootstrap output backend_config_hint
```

State for THIS layer stays local (it holds only infrastructure handles, no app
secrets). The `backend_config_hint` output feeds the app config's
`terraform init -backend-config=...` and the CI workflow. The `tfstate` and
`deployment-plans` containers are created from the runner (over the blob PE) by
the deploy workflow. CLI-requested plans use immutable run-specific blob paths;
their metadata carries a one-hour logical expiry and never includes target ids
or secret values. Each new CLI plan run deletes allowlisted plan blobs older
than 24 hours under a bounded scan/delete cap; it never targets `tfstate` or an
unknown blob path.

## Runner registration

Two options:

1. **Manual (recommended)** - leave `github_runner_token` empty, then on the VM
   (reach it via `az vm run-command invoke` or Azure Bastion):

   ```bash
   cd ~/actions-runner
   sudo -u <runner_user> ./config.sh --url https://github.com/<owner>/<repo> \
     --token <short-lived-token> --labels self-hosted,fdai-deploy
   sudo ./svc.sh install <runner_user> && sudo ./svc.sh start
   ```

2. **Auto** - pass `github_runner_url` + `github_runner_token`. The token is
   short-lived (~1h) and lands in the VM's `custom_data`; prefer manual for
   long-lived hygiene.

The runner authenticates to Azure with `az login --identity` (its system MI) -
no cloud credentials are stored on the box.

## Security notes

- The runner MI uses app-RG Contributor for resource mutation. Its subscription-scope role is
   limited to Event Grid system-topic and subscription management for realtime inventory; it is not subscription
   Contributor. The deploy workflow clears the Azure CLI account cache before each managed-identity
   login so newly granted roles are reflected in Terraform provider tokens.
- No public IP; access is Bastion / run-command / serial console.
- The state account is private + versioned; a bad apply is recoverable.
- `bootstrap.tfvars` and `*.tfstate` are gitignored - never commit them.
