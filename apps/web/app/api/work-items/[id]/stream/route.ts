// EXAMPLE SLICE: live item state over Server-Sent Events (03/F35–F37, FL9).
// Authenticated by the session cookie only; credentials in the URL are refused. Each event's id is the item
// version, so a reconnecting browser resumes with Last-Event-ID. A heartbeat keeps proxies from closing it, and
// the stream ends once the item reaches a final state.
import { getWorkItem } from "@/lib/api/work-items";
import { getSession } from "@/lib/auth/session";
import { hasCredentialsInQuery } from "@/lib/queries";

export const dynamic = "force-dynamic";

const POLL_MS = 2_000;
const HEARTBEAT_MS = 15_000;
const FINAL = new Set(["approved", "rejected"]);

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (hasCredentialsInQuery(new URL(request.url))) {
    return new Response("Credentials never go in a URL.", { status: 400 });
  }
  const session = await getSession();
  if (!session) return new Response("Sign in first.", { status: 401 });
  const { id } = await params;
  let lastVersion = Number(request.headers.get("last-event-id") ?? 0);
  const encoder = new TextEncoder();

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let closed = false;
      let lastBeat = Date.now();
      const send = (chunk: string) => controller.enqueue(encoder.encode(chunk));
      request.signal.addEventListener("abort", () => {
        closed = true;
      });
      send("retry: 3000\n\n");
      while (!closed) {
        try {
          const item = await getWorkItem(session.accessToken, id);
          if (item.version > lastVersion) {
            lastVersion = item.version;
            send(`id: ${item.version}\nevent: state\ndata: ${JSON.stringify({ state: item.state })}\n\n`);
          }
          if (FINAL.has(item.state)) {
            send("event: end\ndata: {}\n\n");
            break;
          }
        } catch {
          send("event: end\ndata: {}\n\n");
          break;
        }
        if (Date.now() - lastBeat > HEARTBEAT_MS) {
          send(": heartbeat\n\n");
          lastBeat = Date.now();
        }
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-store", Connection: "keep-alive" },
  });
}
