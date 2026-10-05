import type { NextConfig } from "next";

// Next.js settings for the GuardianLens website.
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // @guardianlens/shared ships TypeScript source (no build step), so Next must compile it
  // together with the website's own code.
  transpilePackages: ["@guardianlens/shared"],
};

export default nextConfig;
