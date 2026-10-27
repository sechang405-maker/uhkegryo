import { portfolioGatewayProxy } from "../../lib/portfolio-gateway-proxy.mjs";
import { personalRemoteGatewayProxy } from "../../lib/personal-remote-gateway-proxy.mjs";

export const dynamic = "force-dynamic";
export const maxDuration = 120;
export const runtime = "nodejs";

export function GET(request) {
  if (process.env.PERSONAL_REMOTE_TEST === "1") {
    return personalRemoteGatewayProxy(request, "/service-health");
  }
  return portfolioGatewayProxy(request, "/service-health");
}
