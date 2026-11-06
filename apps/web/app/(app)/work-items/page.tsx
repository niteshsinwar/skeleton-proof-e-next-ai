// EXAMPLE SLICE: the list. Read on the server (03/F6), the cursor lives in the URL (03/F10), every state handled (03/F14).
import Link from "next/link";

import { CreateForm } from "@/components/work-items/forms";
import { PendingBadge } from "@/components/work-items/live";
import { Card, Pill, Table } from "@/components/ui/primitives";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { can, whoAmI } from "@/lib/api/session";
import { listWorkItems, type WorkItemPage } from "@/lib/api/work-items";
import { ApiProblem, newIdempotencyKey } from "@/lib/api/transport";
import { requireSession } from "@/lib/auth/session";
import { TEXT, personLabel, stateLabel, stateTone, whenLabel } from "@/lib/labels";

export default async function WorkItemsPage({ searchParams }: { searchParams: Promise<{ cursor?: string }> }) {
  const session = await requireSession();
  const { cursor } = await searchParams;
  let page: WorkItemPage | null = null;
  let problem: string | null = null;
  const me = whoAmI(session.accessToken);
  try {
    page = await listWorkItems(session.accessToken, cursor);
  } catch (err) {
    problem = err instanceof ApiProblem ? err.detail : TEXT.list.loadFailedFallback;
  }
  const allowed = await me;
  const decides = can(allowed, "work_item.decide");
  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h1 className="text-2xl font-semibold">{TEXT.list.title}</h1>
        {decides ? <PendingBadge /> : null}
      </div>
      <Card title={TEXT.list.newItem}>
        <CreateForm csrf={session.csrf} idempotencyKey={newIdempotencyKey()} />
      </Card>
      <Card title={can(allowed, "work_item.read_all") ? TEXT.list.all : TEXT.list.mine}>
        {problem ? (
          <ErrorState title={TEXT.list.loadFailed} body={TEXT.list.loadFailedBody(problem)} />
        ) : !page || page.items.length === 0 ? (
          <EmptyState title={TEXT.list.empty} body={TEXT.list.emptyBody} />
        ) : (
          <>
            <Table caption={TEXT.list.caption} head={[...TEXT.list.columns]}>
              {page.items.map((item) => (
                <tr key={item.id} className="border-b border-line">
                  <td className="py-3 pr-4">
                    <Link href={`/work-items/${item.id}`} className="font-medium text-accent underline">
                      {item.title}
                    </Link>
                  </td>
                  <td className="py-3 pr-4">
                    <Pill tone={stateTone(item.state)}>{stateLabel(item.state)}</Pill>
                  </td>
                  <td className="py-3 pr-4">{personLabel(item.created_by_name, item.created_by)}</td>
                  <td className="py-3 pr-4 text-ink-muted">{whenLabel(item.created_at)}</td>
                </tr>
              ))}
            </Table>
            {page.next_cursor ? (
              <Link href={`/work-items?cursor=${page.next_cursor}`} className="mt-4 inline-block text-accent underline">
                {TEXT.list.more}
              </Link>
            ) : null}
          </>
        )}
      </Card>
    </>
  );
}
