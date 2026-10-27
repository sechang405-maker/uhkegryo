const OFFLINE = {
  detail: "Personal remote test is not configured.",
  failure_code: "PERSONAL_REMOTE_TEST_OFFLINE",
  retryable: false,
};

const REQUEST_HEADERS_TO_DROP = new Set([
  "accept-encoding", "connection", "content-length", "host", "keep-alive",
  "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
  "x-forwarded-for", "x-forwarded-host", "x-forwarded-port", "x-forwarded-proto",
  "x-personal-remote-gateway-secret",
]);
const RESPONSE_HEADERS_TO_DROP = new Set([
  "connection", "content-length", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "transfer-encoding", "upgrade", "x-personal-remote-gateway-secret",
]);
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const LOGIN_PATHS = new Set(["/api/auth/google/start", "/api/auth/google/callback"]);

function offlineResponse() {
  return Response.json(OFFLINE, { status: 503, headers: { "cache-control": "no-store" } });
}

function exactHttpsOrigin(value) {
  try {
    const url = new URL(value || "");
    if (url.protocol !== "https:" || !url.hostname || url.username || url.password
        || url.pathname !== "/" || url.search || url.hash) return null;
    return url.origin;
  } catch {
    return null;
  }
}

function configuration(env) {
  if (env.PERSONAL_REMOTE_TEST !== "1" || env.PORTFOLIO_MODE === "1") return null;
  const publicOrigin = exactHttpsOrigin(env.PERSONAL_REMOTE_PUBLIC_ORIGIN);
  const gatewayOrigin = exactHttpsOrigin(env.PERSONAL_REMOTE_GATEWAY_ORIGIN);
  const secret = env.PERSONAL_REMOTE_GATEWAY_SECRET || "";
  if (!publicOrigin || !gatewayOrigin || publicOrigin === gatewayOrigin
      || secret.length < 32 || !/^[\x21-\x7e]+$/.test(secret)) return null;
  const timeout = Number(env.PERSONAL_REMOTE_GATEWAY_TIMEOUT_SECONDS || "110");
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 110) return null;
  return { publicOrigin, gatewayOrigin, secret, timeoutMs: timeout * 1000 };
}

function targetUrl(config, upstreamPath, requestUrl) {
  if (!(upstreamPath.startsWith("/api/") || upstreamPath === "/service-health")) return null;
  const incoming = new URL(requestUrl);
  if (incoming.origin !== config.publicOrigin) return null;
  const target = new URL(
    upstreamPath === "/service-health" ? "/health" : upstreamPath,
    `${config.gatewayOrigin}/`,
  );
  target.search = new URLSearchParams(incoming.searchParams).toString();
  return target;
}

function requestHeaders(request, config, upstreamPath) {
  const origin = request.headers.get("origin");
  if (origin !== null && origin !== config.publicOrigin) return null;
  if (!SAFE_METHODS.has(request.method.toUpperCase()) && origin !== config.publicOrigin) return null;
  if (request.headers.get("sec-fetch-site") === "cross-site" && !LOGIN_PATHS.has(upstreamPath)) return null;
  const headers = new Headers();
  for (const [name, value] of request.headers) {
    if (!REQUEST_HEADERS_TO_DROP.has(name.toLowerCase())) headers.append(name, value);
  }
  if (!LOGIN_PATHS.has(upstreamPath)) headers.set("origin", config.publicOrigin);
  headers.set("x-personal-remote-gateway-secret", config.secret);
  return headers;
}

function responseHeaders(headers) {
  const forwarded = new Headers();
  for (const [name, value] of headers) {
    if (!RESPONSE_HEADERS_TO_DROP.has(name.toLowerCase())) forwarded.append(name, value);
  }
  forwarded.set("cache-control", "no-store");
  return forwarded;
}

function redirectAllowed(upstreamPath, location, publicOrigin) {
  try {
    const target = new URL(location);
    if (upstreamPath === "/api/auth/google/start") {
      return target.origin === "https://accounts.google.com";
    }
    if (upstreamPath === "/api/auth/google/callback") return target.origin === publicOrigin;
    return false;
  } catch {
    return false;
  }
}

export function createPersonalRemoteGatewayProxy({ env = process.env, fetchImpl = fetch } = {}) {
  return async function personalRemoteGatewayProxy(request, upstreamPath) {
    const config = configuration(env);
    if (!config) return offlineResponse();
    const target = targetUrl(config, upstreamPath, request.url);
    const headers = requestHeaders(request, config, upstreamPath);
    if (!target || !headers) return offlineResponse();
    const method = request.method.toUpperCase();
    const options = {
      method, headers, redirect: "manual", cache: "no-store",
      signal: AbortSignal.timeout(config.timeoutMs),
    };
    if (!SAFE_METHODS.has(method)) {
      options.body = request.body;
      options.duplex = "half";
    }
    try {
      const upstream = await fetchImpl(target, options);
      const location = upstream.headers.get("location");
      if (upstream.status >= 300 && upstream.status < 400
          && (!location || !redirectAllowed(upstreamPath, location, config.publicOrigin))) {
        return offlineResponse();
      }
      return new Response(upstream.body, {
        status: upstream.status,
        statusText: upstream.statusText,
        headers: responseHeaders(upstream.headers),
      });
    } catch {
      return offlineResponse();
    }
  };
}

export const personalRemoteGatewayProxy = createPersonalRemoteGatewayProxy();
