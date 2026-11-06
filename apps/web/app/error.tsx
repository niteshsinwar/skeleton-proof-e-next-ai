"use client";
// No stack traces, no ids: what happened and what to do next (03/F44). The failure is reported, never swallowed
// (03/F48): the digest ties it to the server's log line.
import { useEffect } from "react";

import { ErrorState } from "@/components/ui/states";
import { TEXT } from "@/lib/labels";
import { reportClientError } from "@/lib/telemetry";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => reportClientError("render", error.digest ?? error.message), [error]);
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <ErrorState
        title={TEXT.errors.title}
        body={TEXT.errors.body}
        action={
          <button type="button" onClick={reset} className="text-accent underline">
            {TEXT.errors.tryAgain}
          </button>
        }
      />
    </main>
  );
}
