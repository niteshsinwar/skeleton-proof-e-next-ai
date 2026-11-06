// Client errors (03/F48): one JSON log line each, tagged with the release; no personal data, nothing stored here.
// A render error's digest matches the server's own log line for the same failure.
import { ClientError, readBeacon } from "@/lib/beacons";

export async function POST(request: Request) {
  const report = await readBeacon(request, ClientError);
  if (report) console.error(JSON.stringify({ client_error: report.kind, ...report }));
  return new Response(null, { status: 204 });
}
