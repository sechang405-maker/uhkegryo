import { isPortfolioGatewayRequestAllowed } from "./portfolio-gateway-policy.mjs";

export const PORTFOLIO_OFFLINE_MESSAGE =
  "현재 데모 운영 시간이 아닙니다. 평가 시간에 다시 접속해 주세요.";
export const OFFLINE_FAILURE_CODE = "PORTFOLIO_BACKEND_OFFLINE";

const REQUEST_HEADERS_TO_DROP = new Set([
  "accept-encoding",
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "x-portfolio-gateway-secret",
]);

const RESPONSE_HEADERS_TO_DROP = new Set([
  "connection",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function offlineResponse() {
  return Response.json({
    detail: PORTFOLIO_OFFLINE_MESSAGE,
    failure_code: OFFLINE_FAILURE_CODE,
    retryable: false,
    user_message: PORTFOLIO_OFFLINE_MESSAGE,
  }, {
    status: 503,
    headers: { "cache-control": "no-store" },
  });
}

function notFoundResponse() {
  return new Response("Not Found", {
    status: 404,
    headers: {
      "cache-control": "no-store",
      "content-type": "text/plain; charset=utf-8",
    },
  });
}

function gatewayConfiguration(env) {
  const secret = env.PORTFOLIO_GATEWAY_SECRET || "";
  if (secret.length < 32) return null;
  let origin;
  try {
    const parsed = new URL(env.PORTFOLIO_GATEWAY_ORIGIN || "");
    if (
      parsed.protocol !== "https:"
      || !parsed.hostname
      || parsed.username
      || parsed.password
      || parsed.pathname !== "/"
      || parsed.search
      || parsed.hash
    ) return null;
    origin = parsed.origin;
  } catch {
    return null;
  }
  const timeout = Number(env.PORTFOLIO_GATEWAY_TIMEOUT_SECONDS || "110");
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 110) return null;
  return { origin, secret, timeoutMs: timeout * 1000 };
}

function upstreamUrl(origin, upstreamPath, requestUrl) {
  if (!(upstreamPath === "/service-health" || upstreamPath.startsWith("/api/"))) return null;
  const incoming = new URL(requestUrl);
  const target = new URL(upstreamPath, `${origin}/`);
  target.search = new URLSearchParams(incoming.searchParams).toString();
  return target;
}

function forwardedRequestHeaders(headers, secret) {
  const forwarded = new Headers();
  for (const [name, value] of headers) {
    if (!REQUEST_HEADERS_TO_DROP.has(name.toLowerCase())) forwarded.append(name, value);
  }
  forwarded.set("x-portfolio-gateway-secret", secret);
  return forwarded;
}

function forwardedResponseHeaders(headers) {
  const forwarded = new Headers();
  for (const [name, value] of headers) {
    if (!RESPONSE_HEADERS_TO_DROP.has(name.toLowerCase())) forwarded.append(name, value);
  }
  forwarded.set("cache-control", "no-store");
  return forwarded;
}

export function createPortfolioGatewayProxy({ env = process.env, fetchImpl = fetch } = {}) {
  return async function portfolioGatewayProxy(request, upstreamPath) {
    if (!isPortfolioGatewayRequestAllowed(request.method, upstreamPath)) {
      return notFoundResponse();
    }
    const configuration = gatewayConfiguration(env);
    if (!configuration) return offlineResponse();
    const target = upstreamUrl(configuration.origin, upstreamPath, request.url);
    if (!target) return offlineResponse();
    const method = request.method.toUpperCase();
    const options = {
      method,
      headers: forwardedRequestHeaders(request.headers, configuration.secret),
      redirect: "manual",
      cache: "no-store",
      signal: AbortSignal.timeout(configuration.timeoutMs),
    };
    if (method !== "GET" && method !== "HEAD") {
      options.body = request.body;
      options.duplex = "half";
    }
    try {
      const upstream = await fetchImpl(target, options);
      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: forwardedResponseHeaders(upstream.headers),
      });
    } catch {
      return offlineResponse();
    }
  };
}

export const portfolioGatewayProxy = createPortfolioGatewayProxy();
