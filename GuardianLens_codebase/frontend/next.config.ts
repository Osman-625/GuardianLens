// Next.js settings for the website. The shared package (shared/) is plain TypeScript and React
// source, so Next must compile it as part of the site: it is listed in transpilePackages.
import type { NextConfig } from "next";
import { resolve } from "node:path";

// The settings object Next.js reads at build and run time.
const nextConfig: NextConfig = {
  // Extra development checks that surface unsafe React patterns early.
  reactStrictMode: true,
  // The repository root (one level up) is the workspace root, so Turbopack and the build's file
  // tracing can resolve packages that npm installed there, including the shared package.
  turbopack: { root: resolve(__dirname, "..") },
  outputFileTracingRoot: resolve(__dirname, ".."),
  // @guardianlens/shared ships TypeScript source (no build step), so Next must compile it
  // together with the website's own code.
  transpilePackages: ["@guardianlens/shared"],
};

export default nextConfig;
