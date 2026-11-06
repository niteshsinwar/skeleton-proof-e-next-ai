// @vitest-environment jsdom
// Error monitoring with Sentry, chosen at render time (03/F48): Sentry is the transport only when a DSN is set, the
// built-in beacon otherwise, and the call sites never change. It loads on the first error, so pages ship none of it
// until then (03/F26), and only those call sites report.
import { afterEach, describe, expect, it, vi } from "vitest";

const { captureMessage, init } = vi.hoisted(() => ({ captureMessage: vi.fn(), init: vi.fn() })); // vi.mock is hoisted
vi.mock("@sentry/nextjs", () => ({ captureMessage, init }));

import { reportClientError } from "@/lib/telemetry";

const DSN_VAR = "NEXT_PUBLIC_SENTRY_DSN";

describe("error monitoring with Sentry (03/F48)", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    captureMessage.mockReset();
  });

  it("uses the built-in beacon until a DSN is set", () => {
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
    vi.stubEnv(DSN_VAR, "");
    reportClientError("error", "boom");
    expect(beacon).toHaveBeenCalledOnce();
    expect(captureMessage).not.toHaveBeenCalled();
    expect(init).not.toHaveBeenCalled(); // nothing loaded: no error has gone to Sentry yet
  });

  it("loads Sentry on the first error and sends to it, not to the beacon, once a DSN is set", async () => {
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
    vi.stubEnv(DSN_VAR, "https://publickey@o1.ingest.sentry.io/1");
    reportClientError("unhandledrejection", "x".repeat(500));
    await vi.waitFor(() => expect(captureMessage).toHaveBeenCalledOnce());
    expect(init).toHaveBeenCalledOnce();
    expect(init.mock.calls[0]?.[0]).toMatchObject({
      defaultIntegrations: false,
      sendDefaultPii: false,
      tracesSampleRate: 0,
    });
    expect(String(captureMessage.mock.calls[0]?.[0]).length).toBeLessThanOrEqual(320);
    expect(beacon).not.toHaveBeenCalled();
  });
});
