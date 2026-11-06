// EXAMPLE SLICE: the approver badge. Counts items waiting for a decision; the API decides what the caller may see.
import { listWorkItems } from "@/lib/api/work-items";
import { getSession } from "@/lib/auth/session";
import { TEXT } from "@/lib/labels";

export const dynamic = "force-dynamic";

export async function GET() {
  const session = await getSession();
  if (!session) return Response.json({ detail: TEXT.signInFirst }, { status: 401 });
  const page = await listWorkItems(session.accessToken, undefined, 100);
  const count = page.items.filter((i) => i.state === "submitted" && i.created_by !== session.sub).length;
  return Response.json({ count }, { headers: { "Cache-Control": "no-store" } });
}
