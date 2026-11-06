// One transport for the whole app (03/F4): typed by the client generated from packages/contracts/openapi.json.
// Server-only: it carries the session's access token.
import createClient from "openapi-fetch";

import { env } from "@/lib/env";
import { fetchWithBackoff } from "@/lib/http";

import type { paths } from "./generated/schema";

export { ApiProblem, MAX_WAIT_MS, fetchWithBackoff, newIdempotencyKey, problemFrom, retryDelay } from "@/lib/http";
export type { FieldError } from "@/lib/http";

export function api(accessToken: string) {
  return createClient<paths>({
    baseUrl: env().API_URL,
    headers: { Authorization: `Bearer ${accessToken}` },
    fetch: (request: Request) => fetchWithBackoff(request),
  });
}
