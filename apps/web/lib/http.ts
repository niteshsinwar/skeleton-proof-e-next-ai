// Talking to the API, for both web apps: RFC 9457 problems, back-pressure, idempotency keys (03/F4, F34; 02/A5, A6).
// No framework and no secrets here: the Next.js server and the browser (Vite) both use it.

export type FieldError = { loc: (string | number)[]; msg: string };

/** An RFC 9457 problem from the API, with its stable code and a detail that is safe to show (02/A6). */
export class ApiProblem extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly detail: string,
    readonly fields: FieldError[] = [],
    readonly legal: string[] = [],
  ) {
    super(detail);
  }
}

export function problemFrom(status: number, body: unknown): ApiProblem {
  const b = (body ?? {}) as { code?: string; detail?: string; errors?: FieldError[]; legal_transitions?: string[] };
  return new ApiProblem(
    status,
    b.code ?? "unexpected",
    b.detail ?? "Something went wrong; please try again.",
    b.errors ?? [],
    b.legal_transitions ?? [],
  );
}

// Back-pressure (03/F34): a 429 or 503 is retried only when repeating is safe (a read, or a write carrying an
// Idempotency-Key), at most twice, waiting what Retry-After asks or a jittered exponential backoff. A wait longer
// than MAX_WAIT_MS is not slept through inside a request: the problem goes back to the user to retry later.
const RETRY_STATUSES = new Set([429, 503]);
const ATTEMPTS = 3;
const BASE_MS = 200;
export const MAX_WAIT_MS = 5_000;

type Deps = {
  fetch: (request: Request) => Promise<Response>;
  sleep: (ms: number) => Promise<void>;
  random: () => number;
};
const DEFAULT_DEPS: Deps = {
  fetch: (request) => fetch(request),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  random: Math.random,
};

/** Milliseconds to wait before the next attempt, or null when the server asks for longer than we will wait. */
export function retryDelay(
  retryAfter: string | null,
  attempt: number,
  random: () => number = Math.random,
): number | null {
  if (retryAfter !== null) {
    const ms = /^\d+$/.test(retryAfter.trim()) ? Number(retryAfter) * 1000 : Date.parse(retryAfter) - Date.now();
    if (!Number.isNaN(ms)) return ms > MAX_WAIT_MS ? null : Math.max(0, ms);
  }
  return Math.round(random() * Math.min(BASE_MS * 2 ** attempt, MAX_WAIT_MS)); // full jitter
}

export async function fetchWithBackoff(request: Request, deps: Deps = DEFAULT_DEPS): Promise<Response> {
  const safe = ["GET", "HEAD"].includes(request.method) || request.headers.has("Idempotency-Key");
  for (let attempt = 1; ; attempt++) {
    const last = !safe || attempt >= ATTEMPTS;
    const response = await deps.fetch(last ? request : request.clone());
    if (last || !RETRY_STATUSES.has(response.status)) return response;
    const wait = retryDelay(response.headers.get("Retry-After"), attempt, deps.random);
    if (wait === null) return response;
    await response.body?.cancel();
    await deps.sleep(wait);
  }
}

/** A fresh Idempotency-Key per user intent; a retried submission of the same form reuses it (02/A5). */
export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
