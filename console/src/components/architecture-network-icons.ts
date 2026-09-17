import applicationGatewaySource from "../../../tools/architecture-diagrams/assets/azure/application-gateway.svg?raw";
import firewallSource from "../../../tools/architecture-diagrams/assets/azure/firewall.svg?raw";
import loadBalancerSource from "../../../tools/architecture-diagrams/assets/azure/load-balancer.svg?raw";
import networkInterfaceSource from "../../../tools/architecture-diagrams/assets/azure/network-interface.svg?raw";
import networkSecurityGroupSource from "../../../tools/architecture-diagrams/assets/azure/network-security-group.svg?raw";
import privateEndpointSource from "../../../tools/architecture-diagrams/assets/azure/private-endpoint.svg?raw";
import publicIpSource from "../../../tools/architecture-diagrams/assets/azure/public-ip.svg?raw";
import routeTableSource from "../../../tools/architecture-diagrams/assets/azure/route-table.svg?raw";
import subnetSource from "../../../tools/architecture-diagrams/assets/azure/subnet.svg?raw";
import virtualMachineSource from "../../../tools/architecture-diagrams/assets/azure/virtual-machine.svg?raw";
import virtualNetworkSource from "../../../tools/architecture-diagrams/assets/azure/virtual-network.svg?raw";
import virtualNetworkGatewaySource from "../../../tools/architecture-diagrams/assets/azure/virtual-network-gateway.svg?raw";
import { architectureNetworkIconUrlForResourceType } from "./architecture-network-icon-urls";

interface NetworkIconAsset {
  readonly source: string;
}

const asset = (source: string): NetworkIconAsset => ({ source });
const applicationGatewayAsset = asset(applicationGatewaySource);
const firewallAsset = asset(firewallSource);
const loadBalancerAsset = asset(loadBalancerSource);
const networkInterfaceAsset = asset(networkInterfaceSource);
const networkSecurityGroupAsset = asset(networkSecurityGroupSource);
const privateEndpointAsset = asset(privateEndpointSource);
const publicIpAsset = asset(publicIpSource);
const routeTableAsset = asset(routeTableSource);
const subnetAsset = asset(subnetSource);
const virtualMachineAsset = asset(virtualMachineSource);
const virtualNetworkAsset = asset(virtualNetworkSource);
const virtualNetworkGatewayAsset = asset(virtualNetworkGatewaySource);

const NETWORK_ICON_BY_RESOURCE_TYPE: Readonly<Record<string, NetworkIconAsset>> = Object.freeze({
  "compute.vm": virtualMachineAsset,
  "microsoft.compute/virtualmachines": virtualMachineAsset,
  "microsoft.network/applicationgateways": applicationGatewayAsset,
  "microsoft.network/azurefirewalls": firewallAsset,
  "microsoft.network/loadbalancers": loadBalancerAsset,
  "microsoft.network/networkinterfaces": networkInterfaceAsset,
  "microsoft.network/networksecuritygroups": networkSecurityGroupAsset,
  "microsoft.network/privateendpoints": privateEndpointAsset,
  "microsoft.network/publicipaddresses": publicIpAsset,
  "microsoft.network/routetables": routeTableAsset,
  "microsoft.network/virtualnetworkgateways": virtualNetworkGatewayAsset,
  "microsoft.network/virtualnetworks": virtualNetworkAsset,
  "microsoft.network/virtualnetworks/subnets": subnetAsset,
  "network.application-gateway": applicationGatewayAsset,
  "network.firewall": firewallAsset,
  "network.interface": networkInterfaceAsset,
  "network.load-balancer": loadBalancerAsset,
  "network.nsg": networkSecurityGroupAsset,
  "network.private-endpoint": privateEndpointAsset,
  "network.public-ip": publicIpAsset,
  "network.route-table": routeTableAsset,
  "network.subnet": subnetAsset,
  "network.virtual-network-gateway": virtualNetworkGatewayAsset,
  "network.vnet": virtualNetworkAsset,
  subnet: subnetAsset,
  "virtual-network": virtualNetworkAsset,
});
const iconDataUriByUrl = new Map<string, string>();

/** Resolves only reviewed Azure resource types to digest-locked official icons. */
export function architectureNetworkIconForResourceType(type: string): string | undefined {
  return architectureNetworkIconUrlForResourceType(type);
}

/** Accepts SVG-only icon content with no script, foreign content, or external references. */
export function architectureNetworkIconSourceIsSafe(source: string): boolean {
  return source.startsWith("<svg ") &&
    !/<(?:script|foreignObject)\b/iu.test(source) &&
    !/\bsrc\s*=/iu.test(source) &&
    !/\bhref\s*=\s*["'](?!#)/iu.test(source);
}

/** Embeds a reviewed icon for a self-contained downloaded artifact. */
export async function architectureNetworkIconDataUriForResourceType(
  type: string,
): Promise<string | undefined> {
  const icon = NETWORK_ICON_BY_RESOURCE_TYPE[type.trim().toLowerCase()];
  if (!icon) return undefined;
  const url = architectureNetworkIconUrlForResourceType(type);
  if (!url) return undefined;
  const { source } = icon;
  const cached = iconDataUriByUrl.get(url);
  if (cached) return cached;
  if (!architectureNetworkIconSourceIsSafe(source)) {
    throw new Error("Reviewed network icon contains unsupported SVG content");
  }
  const bytes = new TextEncoder().encode(source);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  const dataUri = `data:image/svg+xml;base64,${btoa(binary)}`;
  iconDataUriByUrl.set(url, dataUri);
  return dataUri;
}
