/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits .next/standalone with only the files and node_modules actually
  // reached — the runtime image is a fraction of a full node_modules copy.
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
