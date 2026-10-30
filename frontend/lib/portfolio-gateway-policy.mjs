const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}";
const TERM_ID = "[A-Za-z0-9_-]{1,100}";

const RULES = [
  ["GET", /^\/service-health$/],
  ["POST", /^\/api\/agent$/],
  ["GET", new RegExp(`^/api/jobs/${UUID}$`)],
  ["GET", /^\/api\/sessions$/],
  ["POST", /^\/api\/sessions$/],
  ["GET", new RegExp(`^/api/sessions/${UUID}$`)],
  ["DELETE", new RegExp(`^/api/sessions/${UUID}$`)],
  ["GET", new RegExp(`^/api/sessions/${UUID}/jobs$`)],
  ["GET", new RegExp(`^/api/sessions/${UUID}/conditions$`)],
  ["DELETE", new RegExp(`^/api/sessions/${UUID}/conditions/${TERM_ID}$`)],
  ["POST", /^\/api\/term-search$/],
];

export function isPortfolioGatewayRequestAllowed(method, pathname) {
  const normalizedMethod = String(method || "").toUpperCase();
  return RULES.some(([allowedMethod, pattern]) => (
    allowedMethod === normalizedMethod && pattern.test(pathname)
  ));
}
