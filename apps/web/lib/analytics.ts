// Product analytics (03/F49, 07/O12): named journey events from one registry, packages/contracts/analytics-events.json
// (copied here by `pnpm gen:api`), kept apart from error and performance telemetry. Every property is a declared value
// or a number, so free text, and with it personal data, cannot be sent; an undeclared event or value is dropped.
import REGISTRY from "@/lib/api/generated/analytics-events.json";

export type EventName = keyof typeof REGISTRY.events;
export type EventProps = Record<string, string | number>;

const EVENTS: Record<string, Record<string, readonly string[] | "number">> = REGISTRY.events;

/** Why this event may not be recorded; empty when it may. Pure, so the browser and the server share it. */
export function eventProblems(name: string, props: EventProps): string[] {
  const declared = EVENTS[name];
  if (!declared) return [`unknown event "${name}"`];
  const problems: string[] = [];
  for (const [key, value] of Object.entries(props)) {
    const allowed = declared[key];
    if (allowed === undefined) problems.push(`"${name}" has no property "${key}"`);
    else if (
      allowed === "number" ? typeof value !== "number" || !Number.isFinite(value) : !allowed.includes(String(value))
    )
      problems.push(`"${name}.${key}" does not allow that value`);
  }
  return problems;
}

/** The one log line an accepted event becomes: its own key, never mixed with errors or vitals (07/O10). */
export function eventLine(name: string, props: EventProps, release: string): string {
  return JSON.stringify({ analytics_event: name, props, release });
}

/** Server side (server actions and routes): record an event that happened on the server, e.g. before a redirect. */
export function recordEvent(name: EventName, props: EventProps = {}): void {
  if (eventProblems(name, props).length === 0) {
    console.info(eventLine(name, props, (process.env.NEXT_PUBLIC_RELEASE ?? "dev").slice(0, 64)));
  }
}

/** Browser side: send an event as a beacon to the same-origin route that validates and logs it. */
export function trackEvent(name: EventName, props: EventProps = {}): void {
  if (eventProblems(name, props).length > 0) return;
  const release = (process.env.NEXT_PUBLIC_RELEASE ?? "dev").slice(0, 64);
  navigator.sendBeacon?.("/api/events", JSON.stringify({ name, props, release }));
}
