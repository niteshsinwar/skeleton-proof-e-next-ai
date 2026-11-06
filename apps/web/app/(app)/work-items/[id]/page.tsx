// EXAMPLE SLICE: one item as a journey (03/F18): what's done, what's next, who holds it; actions only for those
// allowed to take them (the API still decides; hiding a button is never the control, 03/F9).
import Link from "next/link";
import { notFound } from "next/navigation";

import { Journey } from "@/components/shell/journey";
import { WorkItemBrief } from "@/components/work-items/brief";

import { CommandForm } from "@/components/work-items/forms";
import { LiveState } from "@/components/work-items/live";
import { Card } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/states";
import { getAiStatus } from "@/lib/api/ai";
import { can, whoAmI } from "@/lib/api/session";
import { getWorkItem, type WorkItem } from "@/lib/api/work-items";
import { ApiProblem, newIdempotencyKey } from "@/lib/api/transport";
import { requireSession } from "@/lib/auth/session";
import { TEXT, personLabel, whenLabel, type WorkItemState } from "@/lib/labels";

export default async function WorkItemPage({ params }: { params: Promise<{ id: string }> }) {
  const session = await requireSession();
  const { id } = await params;
  let item: WorkItem;
  const me = whoAmI(session.accessToken);
  try {
    item = await getWorkItem(session.accessToken, id);
  } catch (err) {
    if (err instanceof ApiProblem && err.status === 404) notFound();
    return <ErrorState title={TEXT.item.loadFailed} body={TEXT.item.loadFailedBody} />;
  }
  const isOwner = item.created_by === session.sub;
  const canDecide = can(await me, "work_item.decide") && !isOwner && item.state === "submitted";
  const common = { id: item.id, version: item.version, csrf: session.csrf };
  // The assistant's state is read every time, so an off or unreachable assistant is always shown (01/R5).
  const ai = await getAiStatus(session.accessToken).catch(() => null);
  const brief = ai?.steps.find((s) => s.name === "work_item_brief");
  return (
    <>
      <Link href="/work-items" className="text-accent underline">
        {TEXT.item.back}
      </Link>
      <div className="flex flex-wrap items-center gap-4">
        <h1 className="text-2xl font-semibold">{item.title}</h1>
        <LiveState id={item.id} initial={item.state} />
      </div>
      <Journey state={item.state as WorkItemState} />
      <Card title={TEXT.item.details}>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2">
          <dt className="text-ink-muted">{TEXT.item.owner}</dt>
          <dd>{personLabel(item.created_by_name, item.created_by)}</dd>
          <dt className="text-ink-muted">{TEXT.item.created}</dt>
          <dd>{whenLabel(item.created_at)}</dd>
          <dt className="text-ink-muted">{TEXT.item.decidedBy}</dt>
          <dd>{personLabel(item.decided_by_name, item.decided_by)}</dd>
          {item.decision_reason ? (
            <>
              <dt className="text-ink-muted">{TEXT.item.reason}</dt>
              <dd className="measure">{item.decision_reason}</dd>
            </>
          ) : null}
        </dl>
      </Card>
      {isOwner && item.state === "draft" ? (
        <Card title={TEXT.item.nextStep}>
          <CommandForm {...common} command="submit" idempotencyKey={newIdempotencyKey()} />
        </Card>
      ) : null}
      <WorkItemBrief
        id={item.id}
        csrf={session.csrf}
        available={brief?.available ?? false}
        switchedOn={(ai?.switched_on ?? false) && (brief?.switched_on ?? false)}
      />
      {canDecide ? (
        <Card title={TEXT.item.yourDecision}>
          <div className="flex flex-col gap-6">
            <CommandForm {...common} command="approve" idempotencyKey={newIdempotencyKey()} />
            <CommandForm {...common} command="reject" idempotencyKey={newIdempotencyKey()} />
          </div>
        </Card>
      ) : null}
    </>
  );
}
