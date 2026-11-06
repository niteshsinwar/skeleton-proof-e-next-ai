// Every data component ships these three states, or it doesn't merge (03/F14, F44, F45).
import type { ReactNode } from "react";

/** Empty states teach: what this is, and the first action. */
export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div role="status" className="flex flex-col items-start gap-3 rounded-ui border border-dashed border-line p-6">
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="measure text-ink-muted">{body}</p>
      {action}
    </div>
  );
}

/** Errors are visible, say what to do next, and never show stack traces or ids. */
export function ErrorState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 rounded-ui border border-bad p-6">
      <h3 className="text-lg font-semibold text-bad">{title}</h3>
      <p className="measure">{body}</p>
      {action}
    </div>
  );
}

/** Skeleton rows that match the final layout, so nothing shifts when data arrives (03/F27). */
export function LoadingState({ rows = 3, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="flex flex-col gap-3">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-11 animate-pulse rounded-ui bg-line" />
      ))}
    </div>
  );
}
