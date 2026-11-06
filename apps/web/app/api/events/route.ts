// Product analytics events from the browser (03/F49): size-capped, checked against the registry, one log line each
// under its own key; nothing stored here, no personal data. Server-side events use recordEvent in lib/analytics.ts.
import { z } from "zod";

import { eventLine, eventProblems } from "@/lib/analytics";
import { readBeacon } from "@/lib/beacons";

const Beacon = z.object({
  name: z.string().max(80),
  props: z.record(z.string().max(40), z.union([z.string().max(80), z.number()])),
  release: z.string().max(64),
});

export async function POST(request: Request) {
  const event = await readBeacon(request, Beacon);
  if (event && eventProblems(event.name, event.props).length === 0) {
    console.info(eventLine(event.name, event.props, event.release));
  }
  return new Response(null, { status: 204 });
}
