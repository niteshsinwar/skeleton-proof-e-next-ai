// EXAMPLE SLICE: one module per resource (03/F4). Every API operation the UI uses is called from here,
// which is what the API ↔ UI sync check reads (03/F5).
import type { Command } from "@/lib/forms";

import type { components } from "./generated/schema";
import { api, problemFrom } from "./transport";

export type WorkItem = components["schemas"]["WorkItemOut"];
export type WorkItemPage = components["schemas"]["WorkItemPage"];

export async function listWorkItems(token: string, cursor?: string, limit = 20): Promise<WorkItemPage> {
  const { data, error, response } = await api(token).GET("/work-items", {
    params: { query: { limit, ...(cursor ? { cursor } : {}) } },
  });
  if (!data) throw problemFrom(response.status, error);
  return data;
}

export async function getWorkItem(token: string, id: string): Promise<WorkItem> {
  const { data, error, response } = await api(token).GET("/work-items/{item_id}", {
    params: { path: { item_id: id } },
  });
  if (!data) throw problemFrom(response.status, error);
  return data;
}

export async function createWorkItem(token: string, title: string, idempotencyKey: string): Promise<WorkItem> {
  const { data, error, response } = await api(token).POST("/work-items", {
    body: { title },
    headers: { "Idempotency-Key": idempotencyKey },
  });
  if (!data) throw problemFrom(response.status, error);
  return data;
}

export async function runCommand(
  token: string,
  id: string,
  command: Command,
  version: number,
  idempotencyKey: string,
  reason?: string,
): Promise<WorkItem> {
  const headers = { "If-Match": `"${version}"`, "Idempotency-Key": idempotencyKey };
  const path = { item_id: id };
  const result =
    command === "submit"
      ? await api(token).POST("/work-items/{item_id}/submit", { params: { path }, headers })
      : command === "approve"
        ? await api(token).POST("/work-items/{item_id}/approve", { params: { path }, headers, body: { reason } })
        : await api(token).POST("/work-items/{item_id}/reject", { params: { path }, headers, body: { reason } });
  if (!result.data) throw problemFrom(result.response.status, result.error);
  return result.data;
}
