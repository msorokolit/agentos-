/** @type {import('next').NextConfig} */
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const wsUrl = apiUrl.replace(/^http/, "ws");

// Next.js dev / Fast Refresh injects code via `eval`, so we relax
// `script-src` only when running `next dev`. Production builds keep the
// strict CSP.
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";
const connectSrc = isDev
  ? `connect-src 'self' ${apiUrl} ${wsUrl} ws://127.0.0.1:3000 ws://localhost:3000`
  : `connect-src 'self' ${apiUrl} ${wsUrl}`;

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    // Self-only for scripts in production; inline styles allowed (the inline-
    // style helpers we use). The api-gateway and its WS upgrade endpoint are
    // explicitly permitted via connect-src. Dev mode also allows
    // ``unsafe-eval`` for Next.js Fast Refresh and the HMR WebSocket on
    // ``ws://127.0.0.1:3000``.
    value: [
      "default-src 'self'",
      scriptSrc,
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self' data:",
      connectSrc,
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; "),
  },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  {
    key: "Permissions-Policy",
    value: "geolocation=(), microphone=(), camera=()",
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains",
  },
];

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
