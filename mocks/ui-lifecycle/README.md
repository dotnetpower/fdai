# Lifecycle Hub concept screens

These static pages show how operators could see and act on the
[Hub-managed lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md) that
[ADR-0003](../../docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md)
accepted. ADR-0003 and its owner documents define behavior but no screens, so every layout here is
a proposal for review under [#1945](https://github.com/dotnetpower/fdai/issues/1945).

The pages are plain HTML and CSS, English-only, and read-only. Every name, version, digest, and
address is a synthetic placeholder. They execute nothing.

## Open the screens

Open [index.html](index.html) directly, or use the **Lifecycle Hub (ADR-0003)** family in the
repository-root design mock index. Inside a screen, Left and Right page through the story, and
Escape returns to the index.

## Screens

The screens follow one story: a Release fails on a canary and is recalled, a fixed Release is
promoted and reaches a connected installation, the customer changes configuration, and an offline
site imports the same Release.

| Page | Surface | Shows |
|------|---------|-------|
| [01-vendor-release.html](01-vendor-release.html) | Vendor Release catalog | Release images, signature, scan, schema range, health criteria, and capability maximums |
| [02-vendor-release-activity.html](02-vendor-release-activity.html) | Vendor Release catalog | Canary failure, recall, and roll-off |
| [03-vendor-channels.html](03-vendor-channels.html) | Vendor Release catalog | Channels and promotion criteria |
| [04-vendor-fleet.html](04-vendor-fleet.html) | Vendor Release catalog | Lifecycle metadata of connected installations |
| [05-hub-installations.html](05-hub-installations.html) | Lifecycle Hub | Installations, targets, and next windows |
| [06-hub-installation-prod.html](06-hub-installation-prod.html) | Lifecycle Hub | Constraint results and Entities |
| [07-hub-plan.html](07-hub-plan.html) | Lifecycle Hub | Fenced Plan phases, receipts, and verification |
| [08-console-version.html](08-console-version.html) | FDAI Console | Read-only version tab |
| [09-git-config-pr.html](09-git-config-pr.html) | Customer repository | Configuration change as a reviewed merge |
| [10-hub-confirmations.html](10-hub-confirmations.html) | Lifecycle Hub | Azure resource replacement confirmation |
| [11-hub-commands.html](11-hub-commands.html) | Lifecycle Hub | Suppression, authority-lowering, and break-glass commands |
| [12-targethub-bundle-import.html](12-targethub-bundle-import.html) | Offline Target Hub | Upgrade bundle verification and import |
| [13-hub-enrollment.html](13-hub-enrollment.html) | Lifecycle Hub | Enrollment with unmanaged Entities |
| [14-console-policy.html](14-console-policy.html) | FDAI Console | Approval profile, validation, and promotions |

## What the screens assume

- The Hub UI is a separate web app served by the Hub, not a Console route family. The
  [code-location spike](https://github.com/dotnetpower/fdai/issues/1948) records this proposal.
- A reviewed merge in customer Git is the configuration change request, so the Hub asks only for
  destructive-change, uninstall, and enrollment decisions.
- A central Hub cell shows coarse health bands, never event content or operational metrics.
- Release health criteria and automatic recall on a canary failure aren't in the design yet.
  [#1947](https://github.com/dotnetpower/fdai/issues/1947) owns the signing question that automatic
  recall depends on.

The styles import the shared Calm Slate tokens from [`ui/`](../../ui/) and add only
screen-specific composition in [assets/lifecycle.css](assets/lifecycle.css).
