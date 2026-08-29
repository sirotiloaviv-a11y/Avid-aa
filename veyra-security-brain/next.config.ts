import type { NextConfig } from "next";

/**
 * Response headers applied to every route.
 *
 * These are defence-in-depth defaults. They are deliberately conservative
 * rather than convenient — do not relax them to work around a local
 * development problem.
 *
 * Content-Security-Policy is intentionally NOT set here yet: a correct policy
 * for the App Router needs per-request nonces threaded through middleware, and
 * a placeholder policy that has to be loosened later is worse than none. It is
 * tracked as a task for the phase that introduces the first real pages.
 */
const securityHeaders = [
  // Deny framing outright; the app is never intended to be embedded.
  { key: "X-Frame-Options", value: "DENY" },
  // Stop browsers from MIME-sniffing a response away from its declared type.
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Send the origin only, and never to a less-secure destination.
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Drop ambient access to hardware we never use.
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
  // Opt out of cross-origin isolation leaks.
  { key: "X-DNS-Prefetch-Control", value: "off" },
];

// HSTS is production-only: sending it from http://localhost would pin the
// developer's browser to HTTPS for localhost and break every other local app.
const productionOnlyHeaders = [
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Do not leak the framework version to clients.
  poweredByHeader: false,

  typescript: {
    // Never ship a build that does not typecheck.
    ignoreBuildErrors: false,
  },

  eslint: {
    // Never ship a build that does not lint.
    ignoreDuringBuilds: false,
  },

  async headers() {
    return [
      {
        source: "/:path*",
        headers:
          process.env.NODE_ENV === "production"
            ? [...securityHeaders, ...productionOnlyHeaders]
            : securityHeaders,
      },
    ];
  },
};

export default nextConfig;
