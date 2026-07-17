/** @type {import('next').NextConfig} */

const isDev = process.env.NODE_ENV === "development";

/**
 * Escape hatch: set HEADERLESS=1 to disable all security headers (e.g. when
 * debugging locally behind proxies/tooling that the CSP would block).
 *
 * NOTE: `headers()` is evaluated when the config loads. With `next dev` the
 * env var takes effect at server startup (HEADERLESS=1 npm run dev). With
 * `next start` the headers are baked into routes-manifest.json at build time,
 * so the flag must be present during `next build`, not at `next start`.
 */
const headerless =
  process.env.HEADERLESS === "1" || process.env.NEXT_PUBLIC_HEADERLESS === "1";

/** Origin of the backend API, allowed in connect-src when cross-origin. */
const apiOrigin = (() => {
  try {
    return process.env.NEXT_PUBLIC_API_URL
      ? new URL(process.env.NEXT_PUBLIC_API_URL).origin
      : null;
  } catch {
    return null;
  }
})();

const connectSrc = [
  "'self'",
  apiOrigin,
  // When NEXT_PUBLIC_API_URL is unset, the browser client (lib/api.ts
  // getDefaultApiBaseUrl) falls back to http://<localhost|127.0.0.1>:8000
  // whenever the app is served on port 3000. The CSP must mirror that
  // fallback, otherwise the app blocks its own API calls (e2e/CI and the
  // default local dev setup both run with the env unset).
  ...(apiOrigin ? [] : ["http://localhost:8000", "http://127.0.0.1:8000"]),
  // Dev server HMR uses a websocket; ws: is required in some browsers even
  // for same-origin websocket upgrades.
  isDev ? "ws:" : null,
]
  .filter(Boolean)
  .join(" ");

const contentSecurityPolicy = [
  "default-src 'self'",
  // Next.js injects inline bootstrap scripts (hydration); dev mode
  // additionally needs eval for react-refresh/HMR source maps.
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  // Next inlines style tags for CSS-in-JS and font optimization.
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src ${connectSrc}`,
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
];

const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  ...(headerless
    ? {}
    : {
        async headers() {
          return [{ source: "/:path*", headers: securityHeaders }];
        },
      }),
};

export default nextConfig;
