// Client queries declare their freshness and their polling rules explicitly (03/F31, F32, F34).
import { queryOptions } from "@tanstack/react-query";

export type Pending = { count: number };

export async function fetchPending(): Promise<Pending> {
  const res = await fetch("/api/work-items/pending", { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`pending: ${res.status}`);
  return (await res.json()) as Pending;
}

export const PENDING_POLL_MS = 30_000;

/**
 * The approver's "waiting for a decision" count: changes on its own over minutes, so it is polled, but
 * never while the tab is hidden, never on focus storms, and it stops after an error instead of
 * hammering a struggling backend.
 */
export function pendingQuery(fetcher: () => Promise<Pending> = fetchPending) {
  return queryOptions({
    queryKey: ["work-items", "pending"],
    queryFn: fetcher,
    staleTime: PENDING_POLL_MS,
    refetchInterval: (query) => (query.state.status === "error" ? false : PENDING_POLL_MS),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}

/** Realtime URLs never carry credentials: the session cookie authenticates the stream (03/F36). */
export function streamUrl(itemId: string): string {
  return `/api/work-items/${encodeURIComponent(itemId)}/stream`;
}

export function hasCredentialsInQuery(url: URL): boolean {
  return ["token", "access_token", "id_token", "authorization", "session"].some((k) => url.searchParams.has(k));
}
