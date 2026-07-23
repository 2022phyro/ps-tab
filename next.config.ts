import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {/* config options here */};

export default withSentryConfig(nextConfig, {
  silent: true,
  // Source map upload needs SENTRY_AUTH_TOKEN + org/project — set these up
  // once a real Sentry project exists; harmless no-op without them.
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  widenClientFileUpload: true,
});
