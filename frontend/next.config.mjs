import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const apiOrigin = (process.env.AGENT_API_ORIGIN || "http://127.0.0.1:8000").replace(/\/$/, "");
const frontendRoot = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = dirname(frontendRoot);

const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  turbopack: { root: repositoryRoot },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
