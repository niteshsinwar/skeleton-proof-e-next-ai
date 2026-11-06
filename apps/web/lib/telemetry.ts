// Browser telemetry that stays ours (03/F26, F48): small JSON beacons to same-origin routes, no personal data.
// The path is sent without its query string; messages are cut short. A vendor SDK (Sentry or GlitchTip, 13)
// replaces the transport when the project picks one; the call sites stay the same. No Zod here: this module
// ships to the browser, and the routes validate what arrives (lib/beacons.ts).

export const CLIENT_ERROR_KINDS = ["error", "unhandledrejection", "resource", "render"] as const;
export type ClientErrorKind = (typeof CLIENT_ERROR_KINDS)[number];

type SentrySdk = typeof import("@sentry/nextjs");
let sentry: Promise<SentrySdk> | undefined;

// Sentry (03/F48, chosen at render time) loads on the first error, so a page that has none ships none of it: eagerly
// it cost about 35 KB of compressed JavaScript on every route (the budget, 03/F26). Only these call sites report
// (its default integrations are off), so an error is never sent twice; no personal data, no tracing (07/O9 owns traces);
// the release is the git SHA, so each error names the build it came from.
function loadSentry(dsn: string): Promise<SentrySdk> {
  sentry ??= import("@sentry/nextjs").then((sdk) => {
    sdk.init({
      dsn,
      release: process.env.NEXT_PUBLIC_RELEASE,
      defaultIntegrations: false,
      sendDefaultPii: false,
      tracesSampleRate: 0,
      tunnel: "/sentry-tunnel", // same origin (next.config.ts), so the CSP keeps connect-src 'self' (03/F38)
    });
    return sdk;
  });
  return sentry;
}

export function reportClientError(kind: ClientErrorKind, message: string): void {
  // With a DSN, Sentry is the transport: the same call sites, its grouping and source maps.
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  if (dsn) {
    const text = `${kind}: ${message.slice(0, 300)}`;
    void loadSentry(dsn).then((sdk) => sdk.captureMessage(text, "error"));
    return;
  }
  const body = {
    kind,
    message: message.slice(0, 300),
    path: window.location.pathname.slice(0, 200),
    release: (process.env.NEXT_PUBLIC_RELEASE ?? "dev").slice(0, 64),
  };
  navigator.sendBeacon?.("/api/errors", JSON.stringify(body));
}
