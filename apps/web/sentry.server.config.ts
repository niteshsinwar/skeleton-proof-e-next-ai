// Server-side error monitoring with Sentry (03/F48): off until SENTRY_DSN is set at run time; no personal data.
import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: process.env.SENTRY_DSN,
  enabled: Boolean(process.env.SENTRY_DSN),
  release: process.env.NEXT_PUBLIC_RELEASE,
  sendDefaultPii: false,
  tracesSampleRate: 0,
});
