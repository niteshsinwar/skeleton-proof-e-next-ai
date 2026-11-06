// Logic both web apps share (03/F1: logic lives in lib/ and is unit-tested): labels, polling rules, back-pressure,
// session timing.
import { describe, expect, it } from "vitest";

import { MAX_WAIT_MS, fetchWithBackoff, retryDelay } from "@/lib/http";
import { WORK_ITEM_STATES, personLabel, stateLabel, stateTone } from "@/lib/labels";
import { hasCredentialsInQuery, pendingQuery, streamUrl } from "@/lib/queries";
import { WARN_BEFORE_MS, nextCheckIn, sessionPhase } from "@/lib/session-timing";

describe("labels (03/F16)", () => {
  it("gives every state a reader's word and a tone, never the raw value", () => {
    for (const state of WORK_ITEM_STATES) {
      expect(stateLabel(state)).not.toBe(state);
      expect(stateLabel(state)).toMatch(/^[A-Z]/);
      expect(["neutral", "caution", "ok", "bad"]).toContain(stateTone(state));
    }
    expect(stateLabel("something_new")).toBe("Unknown");
    expect(personLabel("Alice Smith", "a7f3c9e1-opaque-subject")).toBe("Alice Smith");
    expect(personLabel(null, "a7f3c9e1-opaque-subject")).toBe("Unknown person"); // never the subject itself
    expect(personLabel(" ", "a7f3c9e1-opaque-subject")).toBe("Unknown person");
    expect(personLabel(null, null)).toBe("Nobody yet");
  });
});

describe("polling and realtime (03/F32, F34, F36)", () => {
  it("never polls in the background or on focus, and stops after an error", () => {
    const q = pendingQuery(async () => ({ count: 0 }));
    expect(q.refetchIntervalInBackground).toBe(false);
    expect(q.refetchOnWindowFocus).toBe(false);
    expect(q.staleTime).toBeGreaterThan(0);
    const interval = q.refetchInterval as (query: { state: { status: string } }) => number | false;
    expect(interval({ state: { status: "success" } })).toBeGreaterThan(0);
    expect(interval({ state: { status: "error" } })).toBe(false);
  });

  it("keeps credentials out of realtime URLs", () => {
    expect(streamUrl("abc")).toBe("/api/work-items/abc/stream");
    expect(hasCredentialsInQuery(new URL("http://x/api/s?access_token=t"))).toBe(true);
    expect(hasCredentialsInQuery(new URL("http://x/api/s?cursor=2"))).toBe(false);
  });
});

function response(status: number, retryAfter?: string): Response {
  return new Response("{}", { status, headers: retryAfter ? { "Retry-After": retryAfter } : {} });
}

function harness(statuses: Response[]) {
  const calls: string[] = [];
  const waits: number[] = [];
  const deps = {
    fetch: async (request: Request) => {
      calls.push(`${request.method} ${await request.text()}`);
      return statuses.shift() ?? response(200);
    },
    sleep: async (ms: number) => void waits.push(ms),
    random: () => 0.5,
  };
  return { calls, waits, deps };
}

describe("back-pressure (03/F34)", () => {
  it("retries a read after a 429, waiting what Retry-After asks", async () => {
    const h = harness([response(429, "2"), response(200)]);
    const result = await fetchWithBackoff(new Request("http://api/x"), h.deps);
    expect(result.status).toBe(200);
    expect(h.calls).toHaveLength(2);
    expect(h.waits).toEqual([2000]);
  });

  it("retries a keyed write with its body intact, using jittered backoff without Retry-After", async () => {
    const h = harness([response(503), response(503), response(200)]);
    const request = new Request("http://api/x", {
      method: "POST",
      body: "payload",
      headers: { "Idempotency-Key": "k" },
    });
    expect((await fetchWithBackoff(request, h.deps)).status).toBe(200);
    expect(h.calls).toEqual(["POST payload", "POST payload", "POST payload"]);
    expect(h.waits).toEqual([200, 400]);
  });

  it("never retries an unkeyed write, a non-transient error, or past the attempt limit", async () => {
    const write = harness([response(503)]);
    expect(
      (await fetchWithBackoff(new Request("http://api/x", { method: "POST", body: "p" }), write.deps)).status,
    ).toBe(503);
    expect(write.calls).toHaveLength(1);
    const notTransient = harness([response(400)]);
    expect((await fetchWithBackoff(new Request("http://api/x"), notTransient.deps)).status).toBe(400);
    expect(notTransient.calls).toHaveLength(1);
    const busy = harness([response(429), response(429), response(429), response(200)]);
    expect((await fetchWithBackoff(new Request("http://api/x"), busy.deps)).status).toBe(429);
    expect(busy.calls).toHaveLength(3);
  });

  it("hands a long Retry-After back to the user instead of sleeping through it", async () => {
    expect(retryDelay(String(MAX_WAIT_MS / 1000 + 1), 1)).toBeNull();
    const h = harness([response(429, "60")]);
    expect((await fetchWithBackoff(new Request("http://api/x"), h.deps)).status).toBe(429);
    expect(h.waits).toEqual([]);
    expect(retryDelay(null, 2, () => 1)).toBe(800);
    expect(retryDelay(null, 10, () => 1)).toBe(MAX_WAIT_MS);
  });
});

describe("session timing (03/F40)", () => {
  it("warns only in the last two minutes, then reports the session as ended", () => {
    const exp = 1_000_000; // seconds
    const at = (msBefore: number) => exp * 1000 - msBefore;
    expect(sessionPhase(at(WARN_BEFORE_MS + 1), exp)).toBe("ok");
    expect(sessionPhase(at(WARN_BEFORE_MS), exp)).toBe("warn");
    expect(sessionPhase(at(1), exp)).toBe("warn");
    expect(sessionPhase(at(0), exp)).toBe("ended");
    expect(nextCheckIn(at(WARN_BEFORE_MS + 5_000), exp)).toBe(5_000); // wakes exactly when the warning starts
    expect(nextCheckIn(at(30_000), exp)).toBe(1_000); // then ticks each second for the countdown
    expect(nextCheckIn(at(0), exp)).toBeNull();
  });
});
