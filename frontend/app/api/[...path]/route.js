import { portfolioGatewayProxy } from "../../../lib/portfolio-gateway-proxy.mjs";
import { personalRemoteGatewayProxy } from "../../../lib/personal-remote-gateway-proxy.mjs";

export const dynamic = "force-dynamic";
export const maxDuration = 120;
export const runtime = "nodejs";

function forward(request) {
  const path = new URL(request.url).pathname;
  if (process.env.PERSONAL_REMOTE_TEST === "1") {
    return personalRemoteGatewayProxy(request, path);
  }
  return portfolioGatewayProxy(request, path);
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const HEAD = forward;
export const OPTIONS = forward;
