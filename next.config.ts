import type { NextConfig } from "next";
import {
  BASELINE_SECURITY_HEADERS,
  PRODUCTION_CSP_REPORT_ONLY,
  SENSITIVE_CACHE_HEADERS,
} from "./src/lib/http-security";

const productionBuild = process.env.NODE_ENV === "production";
const prototypesExplicitlyEnabled =
  process.env.ORACLE_ENABLE_UI_PROTOTYPES === "1";

if (productionBuild && prototypesExplicitlyEnabled) {
  throw new Error(
    "ORACLE_ENABLE_UI_PROTOTYPES no puede habilitarse en una compilación productiva.",
  );
}

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  turbopack: { root: process.cwd() },
  allowedDevOrigins: ["127.0.0.1"],
  async headers() {
    const globalHeaders = productionBuild
      ? [
          ...BASELINE_SECURITY_HEADERS,
          {
            key: "Content-Security-Policy-Report-Only",
            value: PRODUCTION_CSP_REPORT_ONLY,
          },
        ]
      : BASELINE_SECURITY_HEADERS;
    return [
      { source: "/:path*", headers: globalHeaders },
      { source: "/app/:path*", headers: SENSITIVE_CACHE_HEADERS },
      { source: "/platform/:path*", headers: SENSITIVE_CACHE_HEADERS },
      { source: "/login", headers: SENSITIVE_CACHE_HEADERS },
      { source: "/forgot-password", headers: SENSITIVE_CACHE_HEADERS },
      { source: "/reset-password", headers: SENSITIVE_CACHE_HEADERS },
      { source: "/accept-invitation", headers: SENSITIVE_CACHE_HEADERS },
      { source: "/invite", headers: SENSITIVE_CACHE_HEADERS },
    ];
  },
  async redirects() {
    if (!productionBuild) return [];
    return [
      { source: "/", destination: "/app", permanent: false },
      {
        source: "/concept-a/:path*",
        destination: "/app",
        permanent: false,
      },
      {
        source: "/concept-b/:path*",
        destination: "/app",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    const origin = process.env.ORACLE_API_ORIGIN;
    if (!origin) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${origin.replace(/\/$/, "")}/api/:path*`,
      },
      {
        source: "/health/:path*",
        destination: `${origin.replace(/\/$/, "")}/health/:path*`,
      },
    ];
  },
};

export default nextConfig;
