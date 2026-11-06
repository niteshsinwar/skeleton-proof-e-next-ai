"use server";
// EXAMPLE SLICE: ask the assistant for a brief (a named command, 03/F7). Re-checks the session and the CSRF token
// (03/F39, F40); the answer is never optimistic: the screen waits for the verified result (03/F28).
import { briefWorkItem, type Brief } from "@/lib/api/ai";
import { ApiProblem } from "@/lib/api/transport";
import { requireSession, verifyCsrf } from "@/lib/auth/session";
import { AI_TEXT, TEXT } from "@/lib/labels";

export type BriefState = { brief?: Brief; error?: string };

export async function askForBrief(_: BriefState, form: FormData): Promise<BriefState> {
  const session = await requireSession();
  if (!verifyCsrf(session, form.get("csrf"))) return { error: TEXT.forms.stale };
  const id = form.get("id");
  if (typeof id !== "string") return { error: AI_TEXT.unavailable };
  try {
    return { brief: await briefWorkItem(session.accessToken, id) };
  } catch (err) {
    return { error: err instanceof ApiProblem && err.status !== 503 ? err.detail : AI_TEXT.unavailable };
  }
}
