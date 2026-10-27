import { NextResponse } from "next/server.js";

const PRIVATE_PREFIXES = ["/admin", "/invite", "/transfer"];
const GATEWAY_PREFIXES = ["/api/", "/service-health"];

function notFound() {
  return new Response("Not Found", {
    status: 404,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

function unavailable() {
  return new Response("Service Unavailable", {
    status: 503,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
    },
  });
}

function secretMatches(actual, expected) {
  if (typeof actual !== "string" || typeof expected !== "string" || expected.length < 32) return false;
  const length = Math.max(actual.length, expected.length);
  let mismatch = actual.length ^ expected.length;
  for (let index = 0; index < length; index += 1) {
    mismatch |= (actual.charCodeAt(index) || 0) ^ (expected.charCodeAt(index) || 0);
  }
  return mismatch === 0;
}

export function proxy(request) {
  const pathname = new URL(request.url).pathname;
  if ((process.env.PORTFOLIO_MODE === "1" || process.env.PERSONAL_REMOTE_TEST === "1")
      && PRIVATE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
    return notFound();
  }
  if (process.env.PORTFOLIO_GATEWAY_REQUIRED === "1"
      && GATEWAY_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix))) {
    const expected = process.env.PORTFOLIO_GATEWAY_SECRET || "";
    if (expected.length < 32) return unavailable();
    if (!secretMatches(request.headers.get("x-portfolio-gateway-secret"), expected)) return notFound();
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/admin/:path*",
    "/invite/:path*",
    "/transfer/:path*",
    "/api/:path*",
    "/service-health",
  ],
};
