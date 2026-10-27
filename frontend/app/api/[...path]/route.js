import { portfolioGatewayProxy } from "../../../lib/portfolio-gateway-proxy.mjs";

export const dynamic = "force-dynamic";
export const maxDuration = 120;
export const runtime = "nodejs";

function forward(request) {
  return portfolioGatewayProxy(request, new URL(request.url).pathname);
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
export const HEAD = forward;
export const OPTIONS = forward;
