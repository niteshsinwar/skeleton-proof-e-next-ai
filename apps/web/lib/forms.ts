// What a browser form may send to a server action, parsed with Zod before anything else happens
// (13 "Zod at boundaries"). Structure only: field rules (lengths, required text) belong to the API, so its
// 422 problem stays the one source of truth and the user's input is kept (03/F43).
import { z } from "zod";

export const COMMANDS = ["submit", "approve", "reject"] as const;
export type Command = (typeof COMMANDS)[number];

const text = z.preprocess((v) => (typeof v === "string" ? v : ""), z.string());

const CreateInput = z.object({ title: text, idempotencyKey: z.uuid() });

const CommandInput = z.object({
  command: z.enum(COMMANDS),
  id: z.uuid(),
  version: z.coerce.number().int().positive(),
  idempotencyKey: z.uuid(),
  reason: text,
});

export type CreateInput = z.infer<typeof CreateInput>;
export type CommandInput = z.infer<typeof CommandInput>;

function fields(form: FormData, names: string[]): Record<string, FormDataEntryValue | null> {
  return Object.fromEntries(names.map((name) => [name, form.get(name)]));
}

export function parseCreate(form: FormData): CreateInput | null {
  const parsed = CreateInput.safeParse(fields(form, ["title", "idempotencyKey"]));
  return parsed.success ? parsed.data : null;
}

export function parseCommand(form: FormData): CommandInput | null {
  const parsed = CommandInput.safeParse(fields(form, ["command", "id", "version", "idempotencyKey", "reason"]));
  return parsed.success ? parsed.data : null;
}
