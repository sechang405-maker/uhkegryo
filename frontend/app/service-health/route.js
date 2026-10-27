import { portfolioGatewayProxy } from "../../lib/portfolio-gateway-proxy.mjs";

export const dynamic = "force-dynamic";
export const maxDuration = 120;
export const runtime = "nodejs";

export function GET(request) {
  return portfolioGatewayProxy(request, "/service-health");
}
