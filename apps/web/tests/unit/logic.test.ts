// The Next.js app's own logic: sessions, configuration, form parsing, telemetry routes, CSP. Logic both apps share is
// in shared.test.ts
// (03/F1: logic lives in lib/ and is unit-tested).
import { describe, expect, it } from "vitest";

import { contentSecurityPolicy } from "@/proxy";
import { seal, unseal } from "@/lib/auth/session";
import { signOut } from "@/lib/auth/signout";
import { revokeSession } from "@/lib/api/session";
import { isLoopbackIssuer } from "@/lib/auth/oidc";
import { ClientError, MAX_BEACON_BYTES, VitalReport, readBeacon } from "@/lib/beacons";
import { parseEnv } from "@/lib/env";
import { parseCommand, parseCreate } from "@/lib/forms";

const SECRET = "test-secret-that-is-at-least-32-characters";

describe("sessions (03/F9)", () => {
  it("round-trips, rejects tampering and other keys", async () => {
    const sealed = await seal({ sub: "alice" }, SECRET);
    expect(await unseal(sealed, SECRET)).toEqual({ sub: "alice" });
    const [iv, data] = sealed.split(".");
    const flipped = `${iv}.${data!.slice(0, -2)}${data!.endsWith("AA") ? "BB" : "AA"}`;
    expect(await unseal(flipped, SECRET)).toBeNull();
    expect(await unseal(sealed, `${SECRET}-other`)).toBeNull();
    expect(sealed).not.toContain("alice");
  });

  it("fails closed without a real secret", async () => {
    await expect(seal({ sub: "alice" }, "short")).rejects.toThrow(/SESSION_SECRET/);
  });

  it("accepts plain-HTTP issuers only on loopback", () => {
    expect(isLoopbackIssuer("http://127.0.0.1:9400")).toBe(true);
    expect(isLoopbackIssuer("http://idp.example.com")).toBe(false);
    expect(isLoopbackIssuer("https://idp.example.com")).toBe(false);
  });
});

describe("content security policy (03/F38, FL11)", () => {
  it("allows only nonce-carrying scripts in production", () => {
    const csp = contentSecurityPolicy("abc123", false);
    expect(csp).toContain("script-src 'self' 'nonce-abc123' 'strict-dynamic'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toContain("unsafe-inline");
    expect(csp).not.toContain("unsafe-eval");
    expect(contentSecurityPolicy("abc123", true)).toContain("'unsafe-eval'");
  });
});

const GOOD_ENV = {
  API_URL: "http://127.0.0.1:8000",
  OIDC_ISSUER: "https://idp.example.com",
  OIDC_CLIENT_ID: "web",
  OIDC_CLIENT_SECRET: "client-secret-value",
  SESSION_SECRET: SECRET,
  APP_BASE_URL: "https://app.example.com",
};

describe("configuration (13 Zod at boundaries, 02/B7)", () => {
  it("parses a complete configuration", () => {
    expect(parseEnv(GOOD_ENV).API_URL).toBe("http://127.0.0.1:8000");
  });

  it("fails closed naming the variables, never echoing a value", () => {
    const bad = { ...GOOD_ENV, SESSION_SECRET: "short-secret-value", API_URL: "not a url", OIDC_CLIENT_ID: undefined };
    let message = "";
    try {
      parseEnv(bad);
    } catch (err) {
      message = (err as Error).message;
    }
    expect(message).toBe("Invalid web configuration: API_URL, OIDC_CLIENT_ID, SESSION_SECRET");
    expect(message).not.toContain("short-secret-value");
  });
});

function form(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [k, v] of Object.entries(values)) data.set(k, v);
  return data;
}

const KEY = "0b4f8c3e-6d2a-4f1b-9a7e-2c5d8e9f1a3b"; // gitleaks:allow (an idempotency key in a test, not a secret)

describe("server action input (13 Zod at boundaries, 03/F7)", () => {
  it("accepts a well-formed command and leaves field rules to the API", () => {
    const parsed = parseCommand(form({ command: "approve", id: KEY, version: "3", idempotencyKey: KEY, reason: "" }));
    expect(parsed).toEqual({ command: "approve", id: KEY, version: 3, idempotencyKey: KEY, reason: "" });
    expect(parseCreate(form({ title: "x".repeat(500), idempotencyKey: KEY }))?.title).toHaveLength(500);
  });

  it("refuses unknown commands, malformed ids and versions, and missing keys", () => {
    const base = { command: "approve", id: KEY, version: "3", idempotencyKey: KEY };
    expect(parseCommand(form({ ...base, command: "delete" }))).toBeNull();
    expect(parseCommand(form({ ...base, id: "../admin" }))).toBeNull();
    expect(parseCommand(form({ ...base, version: "0" }))).toBeNull();
    expect(parseCommand(form({ ...base, version: "two" }))).toBeNull();
    expect(parseCreate(form({ title: "A title" }))).toBeNull();
  });
});

function beacon(body: string): Request {
  return new Request("http://web/api/errors", { method: "POST", body });
}

describe("telemetry routes (03/F26, F48)", () => {
  it("accepts a well-formed report", async () => {
    const report = { kind: "error", message: "boom", path: "/work-items", release: "abc123" };
    expect(await readBeacon(beacon(JSON.stringify(report)), ClientError)).toEqual(report);
    const vital = { name: "LCP", value: 812, rating: "good", path: "/" };
    expect(await readBeacon(beacon(JSON.stringify(vital)), VitalReport)).toEqual(vital);
  });

  it("refuses oversized, malformed and wrongly shaped bodies", async () => {
    // Well-formed and the right shape (unknown keys are dropped), so only the size cap can refuse it.
    const padded = { kind: "error", message: "boom", path: "/", release: "dev", pad: "x".repeat(MAX_BEACON_BYTES) };
    expect(await readBeacon(beacon(JSON.stringify({ ...padded, pad: "" })), ClientError)).not.toBeNull();
    expect(await readBeacon(beacon(JSON.stringify(padded)), ClientError)).toBeNull();
    expect(await readBeacon(beacon("{not json"), ClientError)).toBeNull();
    expect(
      await readBeacon(beacon(JSON.stringify({ kind: "anything", message: "", path: "", release: "" })), ClientError),
    ).toBeNull();
    expect(await readBeacon(beacon(JSON.stringify({ name: "LCP", value: -1, path: "/" })), VitalReport)).toBeNull();
  });
});

describe("ending and renewing a session (02/Z4, 03/F40)", () => {
  const session = { sub: "alice", name: "Alice", accessToken: "token-1", exp: 2_000_000_000, csrf: "c" };

  it("signs out by revoking the session's own token first", async () => {
    const calls: string[] = [];
    const out = await signOut(session, async (token) => {
      calls.push(token);
      return true;
    });
    expect(calls).toEqual(["token-1"]);
    expect(out.redirectTo).toBe("/");
  });

  it("says so when the server could not end the session, and still signs out locally", async () => {
    const out = await signOut(session, async () => false);
    expect(out.redirectTo).toBe("/?signout=incomplete");
    expect((await signOut(null, async () => false)).redirectTo).toBe("/");
  });

  it("counts a revoke as done on 204 or 401, and as failed on anything else or a network error", async () => {
    const client = (status: number) => ({
      POST: async () => ({ response: new Response(null, { status: status === 204 ? 204 : status }) }),
    });
    expect(await revokeSession("t", client(204))).toBe(true);
    expect(await revokeSession("t", client(401))).toBe(true); // already revoked or expired: nothing left to end
    expect(await revokeSession("t", client(503))).toBe(false);
    const broken = { POST: async () => Promise.reject(new Error("offline")) };
    expect(await revokeSession("t", broken)).toBe(false);
  });
});
