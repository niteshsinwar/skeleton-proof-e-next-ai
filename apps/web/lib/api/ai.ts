// The generic AI API (04/X6, 06/E10, README #9): one module for every AI screen. Called on the server with the
// session's token; the sync check (03/F5) reads these call sites.
import type { components } from "./generated/schema";
import { api, problemFrom } from "./transport";

export type AIStatus = components["schemas"]["AIStatus"];
export type AttemptView = components["schemas"]["AttemptOut"];
export type Proposal = components["schemas"]["ProposalOut"];
export type Verdict = components["schemas"]["Feedback"]["verdict"];

export async function getAiStatus(token: string): Promise<AIStatus> {
  const { data, error, response } = await api(token).GET("/ai/status");
  if (!data) throw problemFrom(response.status, error);
  return data;
}

export async function getAttempt(token: string, id: string): Promise<AttemptView> {
  const { data, error, response } = await api(token).GET("/ai/attempts/{attempt_id}", {
    params: { path: { attempt_id: id } },
  });
  if (!data) throw problemFrom(response.status, error);
  return data;
}

export async function sendFeedback(token: string, id: string, verdict: Verdict, correction?: string): Promise<void> {
  const { error, response } = await api(token).POST("/ai/attempts/{attempt_id}/feedback", {
    params: { path: { attempt_id: id } },
    body: { verdict, correction: correction || null },
  });
  if (!response.ok) throw problemFrom(response.status, error);
}

export async function listProposals(token: string): Promise<Proposal[]> {
  const { data, error, response } = await api(token).GET("/proposals");
  if (!data) throw problemFrom(response.status, error);
  return data.items;
}

export async function getProposal(token: string, id: string): Promise<Proposal> {
  const { data, error, response } = await api(token).GET("/proposals/{proposal_id}", {
    params: { path: { proposal_id: id } },
  });
  if (!data) throw problemFrom(response.status, error);
  return data;
}

/** One proposal at a time: there is deliberately no bulk decision (03/F20). */
export async function decideProposal(
  token: string,
  id: string,
  approve: boolean,
  version: number,
  idempotencyKey: string,
  reason?: string,
): Promise<Proposal> {
  const headers = { "If-Match": `"${version}"`, "Idempotency-Key": idempotencyKey };
  const params = { path: { proposal_id: id } };
  const body = { reason: reason || null };
  const { data, error, response } = approve
    ? await api(token).POST("/proposals/{proposal_id}/approve", { params, body, headers })
    : await api(token).POST("/proposals/{proposal_id}/reject", { params, body, headers });
  if (!data) throw problemFrom(response.status, error);
  return data;
}

export type Brief = components["schemas"]["BriefOut"];

/** EXAMPLE SLICE: ask for a brief on a work item. A 503 means the assistant is off or unavailable. */
export async function briefWorkItem(token: string, id: string): Promise<Brief> {
  const { data, error, response } = await api(token).POST("/work-items/{item_id}/brief", {
    params: { path: { item_id: id } },
  });
  if (!data) throw problemFrom(response.status, error);
  return data;
}
