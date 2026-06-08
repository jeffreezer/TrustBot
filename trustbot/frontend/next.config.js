/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Defense-in-depth response headers for the web app. The CSP carries frame-ancestors 'none'
  // (anti-clickjacking) without a content allowlist, so it can't break Next's own asset loads;
  // tighten to a full nonce-based CSP if this ever serves untrusted embeds.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
