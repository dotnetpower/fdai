# Isolated development access

This tool connects a Windows and WSL development workstation to FDAI private endpoints through
Azure Point-to-Site (P2S) VPN. It uses its own resource group, VNet, Terraform root, and local
state so the access network can be removed without changing FDAI runtime resources.

## Layout

| Path | Purpose |
|------|---------|
| `infra/` | Independent VPN Gateway, Private DNS Resolver, peering, and DNS links. |
| `scripts/profile.sh` | Generates and validates an Azure VPN Client profile after apply. |
| `scripts/wsl-dns.sh` | Applies or removes Resolver DNS on the current WSL VPN interface. |
| `scripts/doctor.sh` | Verifies WSL networking, private DNS, routing, and optional TCP access. |

## Isolation boundary

The stack creates no FDAI workload identity, role assignment, application setting, private
endpoint, or runtime resource. The only resources placed under an existing FDAI resource group
are one VNet peering child and the requested Private DNS zone links. Destroying this stack removes
those connections before deleting the dedicated development-access resource group.

The FDAI VNet keeps its current DNS servers. Only the development-access VNet uses the Private DNS
Resolver inbound address, which Azure VPN Gateway includes in newly generated client profiles.

> A P2S gateway requires a Standard public IP for the managed VPN service. If tenant policy denies
> every public IP resource, request a scoped policy exemption for this gateway instead of weakening
> the FDAI application network policy.

## Prerequisites

- Terraform 1.9 or later and Azure CLI authenticated to the target subscription.
- Windows 11 22H2 or later with current WSL and Azure VPN Client.
- Permission to create network resources in the development-access resource group and peering and
  DNS links in the FDAI development resource group.
- An Entra Conditional Access policy that permits only the intended developer group to use Azure
  VPN Client and requires MFA. This Terraform root does not create tenant-wide identity policy.
- Non-overlapping CIDRs for the access VNet, VPN clients, FDAI VNet, local LAN, WSL, and Docker.
- The Microsoft-registered Azure VPN Client audience for the active Azure cloud from the
  [P2S Microsoft Entra ID guide](https://learn.microsoft.com/azure/vpn-gateway/point-to-site-entra-gateway).

## Provision the isolated stack

Copy the example to an ignored file and populate only deployment-specific values:

```bash
cd tools/dev-access/infra
cp terraform.tfvars.example dev.tfvars
terraform init
terraform fmt -check
terraform validate
terraform plan -var-file=dev.tfvars -out=dev-access.tfplan
terraform apply dev-access.tfplan
```

Review the plan before apply. Expected changes are confined to the dedicated resource group plus
two child-resource categories on FDAI: VNet peering and Private DNS VNet links. VPN Gateway
provisioning commonly takes 30-45 minutes. New gateways use the availability-zone-capable
`VpnGw1AZ` SKU because Azure no longer accepts new non-AZ `VpnGw1-5` gateways.

Populate `fdai_private_dns_zones` with every FDAI private service needed from the workstation.
Typical deployments link zones for Key Vault, PostgreSQL, Storage Blob/DFS, Event Hubs, and Azure
OpenAI when those services are enabled. Do not link the private Terraform state zone unless local
state access is an explicit requirement.

## Configure Windows and WSL

Set `%UserProfile%\.wslconfig` on Windows:

```ini
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
```

Apply the WSL change from PowerShell:

```powershell
wsl --shutdown
```

Generate the client profile from WSL after Terraform has converged:

```bash
tools/dev-access/scripts/profile.sh
```

Import `tools/dev-access/.profiles/azurevpnconfig.xml` into Azure VPN Client, then connect with the
Entra account authorized by the tenant's Conditional Access and MFA policy.

WSL normally receives the VPN DNS policy through DNS tunneling. If the distribution manages
`/etc/resolv.conf` itself or pins `systemd-resolved` to another DNS service, apply the Resolver to
the mirrored VPN interface after each connection:

```bash
tools/dev-access/scripts/wsl-dns.sh apply
```

The setting belongs to the transient VPN interface. Disconnecting the VPN removes that interface
and restores the distribution's existing DNS behavior. You can remove it before disconnecting with
`tools/dev-access/scripts/wsl-dns.sh revert`.

## Verify private access

Pass real private hostnames at runtime. Hostnames and endpoints are never stored in this repository.

```bash
tools/dev-access/scripts/doctor.sh \
  <private-vault-host> \
  <private-postgres-host>:5432
```

The check fails when WSL mirrored networking is absent, DNS does not resolve, routing is missing,
the Resolver and WSL answers differ, or the optional TCP connection cannot be established.

## Remove development access

Disconnect Azure VPN Client before destroying the stack. Use a saved destroy plan so the FDAI
connections are visible during review:

```bash
cd tools/dev-access/infra
terraform plan -destroy -var-file=dev.tfvars -out=dev-access-destroy.tfplan
terraform apply dev-access-destroy.tfplan
```

The FDAI control plane continues running while the developer-access path is unavailable or removed.
