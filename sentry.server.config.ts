import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.SENTRY_DSN,
  tracesSampleRate: 1.0,
  // Quiet by default in local dev when no DSN is configured yet.
  enabled: !!process.env.SENTRY_DSN,
});
