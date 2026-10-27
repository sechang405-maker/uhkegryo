import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const apiOrigin = (process.env.AGENT_API_ORIGIN || "http://127.0.0.1:8000").replace(/\/$/, "");
const frontendRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = dirname(frontendRoot);
const demoMode = process.env.NEXT_PUBLIC_UI_DEMO || "0";
const gatewayProxy = process.env.PORTFOLIO_GATEWAY_PROXY || "0";
if (!["0", "1"].includes(demoMode)) throw new Error("NEXT_PUBLIC_UI_DEMO must be 0 or 1");
if (!["0", "1"].includes(gatewayProxy)) throw new Error("PORTFOLIO_GATEWAY_PROXY must be 0 or 1");

const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  turbopack: { root: repositoryRoot },
  async rewrites() {
    if (demoMode === "1" || gatewayProxy === "1") return [];
    return {
      beforeFiles: [
        { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
        { source: "/service-health", destination: `${apiOrigin}/health` },
      ],
      afterFiles: [],
      fallback: [],
    };
  },
};

export default nextConfig;

