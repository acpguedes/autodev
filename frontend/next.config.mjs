/** @type {import('next').NextConfig} */

const isDev = process.env.NODE_ENV === "development";

/**
 * Escape hatch: set HEADERLESS=1 to disable all security headers (e.g. when
 * debugging locally behind proxies/tooling that the CSP would block).
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
