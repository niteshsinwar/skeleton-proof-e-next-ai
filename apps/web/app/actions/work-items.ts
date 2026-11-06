"use server";
// EXAMPLE SLICE: named commands as server actions (03/F7). Each one re-checks the session and the CSRF token
// (03/F39, F40), parses the form with Zod (13), sends If-Match and an Idempotency-Key, and returns the user's
// input on failure (03/F43).
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { recordEvent } from "@/lib/analytics";
import { createWorkItem as apiCreate, runCommand } from "@/lib/api/work-items";
import { ApiProblem } from "@/lib/api/transport";
import { requireSession, verifyCsrf } from "@/lib/auth/session";
import { parseCommand, parseCreate, type Command } from "@/lib/forms";
import { TEXT } from "@/lib/labels";

export type FormState = { error?: string; fieldError?: string; done?: Command; values: Record<string, string> };

const STALE = TEXT.forms.stale;

function text(form: FormData, name: string): string {
  const value = form.get(name);
  return typeof value === "string" ? value : "";
}

function failure(err: unknown, values: Record<string, string>): FormState {
  if (err instanceof ApiProblem) {
    const field = err.fields[0]?.msg;
    return { error: err.detail, fieldError: field, values };
  }
  return { error: TEXT.forms.unexpected, values };
}

export async function createWorkItemAction(_: FormState, form: FormData): Promise<FormState> {
  const session = await requireSession();
  const values = { title: text(form, "title") };
  if (!verifyCsrf(session, form.get("csrf"))) return { error: TEXT.forms.otherUser, values };
  const input = parseCreate(form);
  if (!input) return { error: STALE, values };
  let id: string;
  try {
    id = (await apiCreate(session.accessToken, input.title, input.idempotencyKey)).id;
  } catch (err) {
    return failure(err, values);
  }
  recordEvent("work_item.created"); // EXAMPLE: the journey step, recorded here because the redirect ends the request
  revalidatePath("/work-items");
  redirect(`/work-items/${id}`);
}

export async function commandAction(_: FormState, form: FormData): Promise<FormState> {
  const session = await requireSession();
  const values = { reason: text(form, "reason") };
  if (!verifyCsrf(session, form.get("csrf"))) return { error: TEXT.forms.otherUser, values };
  const input = parseCommand(form);
  if (!input) return { error: STALE, values };
  try {
    await runCommand(
      session.accessToken,
      input.id,
      input.command,
      input.version,
      input.idempotencyKey,
      input.reason || undefined,
    );
  } catch (err) {
    return failure(err, values);
  }
  revalidatePath(`/work-items/${input.id}`);
  return { done: input.command, values: {} };
}
