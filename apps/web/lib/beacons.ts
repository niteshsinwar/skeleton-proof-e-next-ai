// What the telemetry routes accept (13 "Zod at boundaries"): these routes are open to anyone, so a body is
// size-capped before it is read and validated before it is logged. Server-only.
import { z } from "zod";

import { CLIENT_ERROR_KINDS } from "@/lib/telemetry";

export const ClientError = z.object({
  kind: z.enum(CLIENT_ERROR_KINDS),
  message: z.string().max(300),
  path: z.string().max(200),
  release: z.string().max(64),
});

export const VitalReport = z.object({
  name: z.enum(["CLS", "FCP", "FID", "INP", "LCP", "TTFB"]),
  value: z.number().nonnegative(),
  rating: z.enum(["good", "needs-improvement", "poor"]).optional(),
  path: z.string().max(200),
});

/** The largest body a telemetry route reads; anything bigger is refused. */
export const MAX_BEACON_BYTES = 2_048;

/** Read and validate a beacon body; null when it is too big, not JSON, or the wrong shape. */
export async function readBeacon<T>(request: Request, schema: z.ZodType<T>): Promise<T | null> {
  if (Number(request.headers.get("content-length") ?? "0") > MAX_BEACON_BYTES) return null;
  const text = await request.text();
  if (text.length > MAX_BEACON_BYTES) return null;
  try {
    const parsed = schema.safeParse(JSON.parse(text));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}
