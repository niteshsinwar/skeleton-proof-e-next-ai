// Field Core Web Vitals (03/F26): one JSON log line per metric, no personal data, nothing stored here.
import { VitalReport, readBeacon } from "@/lib/beacons";

export async function POST(request: Request) {
  const report = await readBeacon(request, VitalReport);
  if (report)
    console.log(JSON.stringify({ metric: report.name, value: report.value, rating: report.rating, path: report.path }));
  return new Response(null, { status: 204 });
}
