// Product analytics (lib/analytics.ts; 03/F49): only declared events and values are recorded, so no free text and no
// personal data reaches the analytics log, and the web copy of the registry never drifts from the contract.
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/events/route";
import { eventLine, eventProblems } from "@/lib/analytics";

const ROOT = join(__dirname, "..", "..");

describe("analytics events (03/F49)", () => {
  afterEach(() => vi.restoreAllMocks());

  it("accepts a declared event with declared values", () => {
    expect(eventProblems("work_item.created", {})).toEqual([]);
    expect(eventProblems("work_item.decided", { outcome: "approved" })).toEqual([]);
  });

  it("refuses an undeclared event, property or value, so free text can't be sent", () => {
    expect(eventProblems("user.signed_up", {})).toEqual(['unknown event "user.signed_up"']);
    expect(eventProblems("work_item.created", { email: "jane@gmail.com" })).toEqual([
      '"work_item.created" has no property "email"',
    ]);
    expect(eventProblems("work_item.decided", { outcome: "Jane Doe said no" })).toEqual([
      '"work_item.decided.outcome" does not allow that value',
    ]);
  });

  it("writes one line under its own key, apart from errors and vitals (07/O10)", () => {
    expect(JSON.parse(eventLine("work_item.created", {}, "abc123"))).toEqual({
      analytics_event: "work_item.created",
      props: {},
      release: "abc123",
    });
  });

  it("keeps the web copy of the registry identical to the contract (regenerate with pnpm gen:api)", () => {
    const contract = readFileSync(join(ROOT, "..", "..", "packages", "contracts", "analytics-events.json"), "utf8");
    const copy = readFileSync(join(ROOT, "lib", "api", "generated", "analytics-events.json"), "utf8");
    expect(copy).toBe(contract);
  });

  it("logs a valid beacon and drops an invalid one without logging it", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const send = (body: unknown) =>
      POST(new Request("http://web/api/events", { method: "POST", body: JSON.stringify(body) }));
    expect((await send({ name: "work_item.created", props: {}, release: "r1" })).status).toBe(204);
    expect((await send({ name: "work_item.created", props: { note: "free text" }, release: "r1" })).status).toBe(204);
    expect((await send({ name: "spoofed", props: {}, release: "r1" })).status).toBe(204);
    expect(info.mock.calls.map((c) => JSON.parse(String(c[0])).analytics_event)).toEqual(["work_item.created"]);
  });
});
