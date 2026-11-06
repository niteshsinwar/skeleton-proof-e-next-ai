"use client";
// EXAMPLE SLICE: live state over SSE (03/F35–F37) and the approver's pending count via a polled query (03/F32).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Pill } from "@/components/ui/primitives";
import { TEXT, stateLabel, stateTone } from "@/lib/labels";
import { pendingQuery, streamUrl } from "@/lib/queries";

/** One EventSource per page; the browser resumes with Last-Event-ID; the session cookie authenticates it. */
export function LiveState({ id, initial }: { id: string; initial: string }) {
  const [state, setState] = useState(initial);
  useEffect(() => {
    const source = new EventSource(streamUrl(id));
    source.addEventListener("state", (event) => {
      const data = JSON.parse((event as MessageEvent<string>).data) as { state: string };
      setState(data.state);
    });
    source.addEventListener("end", () => source.close());
    return () => source.close();
  }, [id]);
  return (
    <span aria-live="polite" data-testid="live-state">
      <Pill tone={stateTone(state)}>{stateLabel(state)}</Pill>
    </span>
  );
}

export function PendingBadge() {
  const { data, status } = useQuery(pendingQuery());
  if (status === "pending") return <span className="text-sm text-ink-muted">{TEXT.live.checking}</span>;
  if (status === "error") return <span className="text-sm text-bad">{TEXT.live.checkFailed}</span>;
  return <span className="text-sm">{data.count === 0 ? TEXT.live.nothingWaiting : TEXT.live.waiting(data.count)}</span>;
}
