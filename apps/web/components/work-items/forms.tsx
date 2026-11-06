"use client";
// EXAMPLE SLICE: forms that keep input on failure, show the error beside the field, and acknowledge at once (03/F43, F44).
import { useActionState } from "react";

import { commandAction, createWorkItemAction, type FormState } from "@/app/actions/work-items";
import { Button, Field } from "@/components/ui/primitives";
import { useToasts } from "@/components/ui/toast";
import { TEXT } from "@/lib/labels";

const EMPTY: FormState = { values: {} };

export function CreateForm({ csrf, idempotencyKey }: { csrf: string; idempotencyKey: string }) {
  const [state, action, pending] = useActionState(createWorkItemAction, EMPTY);
  return (
    <form action={action} className="flex flex-col gap-4" aria-label={TEXT.list.newItem}>
      <input type="hidden" name="csrf" value={csrf} />
      <input type="hidden" name="idempotencyKey" value={idempotencyKey} />
      <Field
        label={TEXT.forms.title}
        name="title"
        required
        hint={TEXT.forms.titleHint}
        defaultValue={state.values.title}
        error={state.fieldError ?? state.error}
      />
      <div>
        <Button type="submit" disabled={pending}>
          {pending ? TEXT.forms.creating : TEXT.forms.create}
        </Button>
      </div>
    </form>
  );
}

const LABEL = TEXT.forms.command;
const DONE = TEXT.forms.done;

export function CommandForm({
  id,
  version,
  command,
  csrf,
  idempotencyKey,
}: {
  id: string;
  version: number;
  command: keyof typeof LABEL;
  csrf: string;
  idempotencyKey: string;
}) {
  const toasts = useToasts();
  // The toast is raised here, not in an effect: a finished command re-renders the page and this form may be gone.
  const [state, action, pending] = useActionState(async (previous: FormState, form: FormData) => {
    const next = await commandAction(previous, form);
    if (next.done) toasts.add({ title: DONE[next.done] });
    return next;
  }, EMPTY);
  return (
    <form action={action} className="flex flex-col gap-3" aria-label={LABEL[command]}>
      <input type="hidden" name="csrf" value={csrf} />
      <input type="hidden" name="idempotencyKey" value={idempotencyKey} />
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="version" value={String(version)} />
      <input type="hidden" name="command" value={command} />
      {command === "reject" ? (
        <Field label={TEXT.forms.reason} name="reason" multiline required defaultValue={state.values.reason} />
      ) : null}
      {state.error ? (
        <p role="alert" className="text-sm text-bad">
          {state.error}
        </p>
      ) : null}
      <div>
        <Button type="submit" variant={command === "reject" ? "danger" : "primary"} disabled={pending}>
          {pending ? TEXT.forms.working : LABEL[command]}
        </Button>
      </div>
    </form>
  );
}
