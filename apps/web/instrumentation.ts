// Next.js instrumentation: start Sentry on the Node.js server and report errors from server components, routes and
// actions (03/F48). The proxy only sets headers, so no edge configuration is needed.
import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }
}

export const onRequestError = Sentry.captureRequestError;
