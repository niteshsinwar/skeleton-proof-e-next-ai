// Owned primitives on unstyled Base UI parts (03/F14, FL4). Tokens only: no literal colours or inline styles.
import { Button as BaseButton } from "@base-ui/react/button";
import { Dialog as BaseDialog } from "@base-ui/react/dialog";
import { Field as BaseField } from "@base-ui/react/field";
import type { ComponentProps, ReactNode } from "react";

import { TEXT } from "@/lib/labels";

const BUTTON = {
  primary: "bg-accent text-accent-ink hover:opacity-90",
  secondary: "border border-line bg-surface text-ink hover:bg-canvas",
  danger: "border border-bad text-bad bg-surface hover:bg-canvas",
} as const;

export function buttonClass(variant: keyof typeof BUTTON = "primary"): string {
  return `inline-flex min-h-11 items-center gap-2 rounded-ui px-4 font-medium transition-opacity disabled:opacity-50 ${BUTTON[variant]}`;
}

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ComponentProps<typeof BaseButton> & { variant?: keyof typeof BUTTON }) {
  return <BaseButton {...props} className={`${buttonClass(variant)} ${className}`} />;
}

export function Field({
  label,
  name,
  error,
  hint,
  defaultValue,
  multiline = false,
  required = false,
  maxLength,
  type = "text",
  autoComplete,
}: {
  label: string;
  name: string;
  error?: string;
  hint?: string;
  defaultValue?: string;
  multiline?: boolean;
  required?: boolean;
  maxLength?: number;
  type?: "text" | "email" | "password";
  autoComplete?: string;
}) {
  // The label is always visible; the error sits beside the field and says what to do; checks run on blur and on
  // submit, never on every keystroke (03/F43).
  const control = "w-full rounded-ui border border-line bg-surface px-3 py-2 text-ink";
  return (
    <BaseField.Root
      name={name}
      invalid={error ? true : undefined}
      validationMode="onBlur"
      className="flex flex-col gap-1"
    >
      <BaseField.Label className="font-medium">{label}</BaseField.Label>
      {multiline ? (
        <BaseField.Control
          render={<textarea rows={3} />}
          defaultValue={defaultValue}
          required={required}
          maxLength={maxLength}
          className={control}
        />
      ) : (
        <BaseField.Control
          type={type}
          autoComplete={autoComplete}
          defaultValue={defaultValue}
          required={required}
          maxLength={maxLength}
          className={control}
        />
      )}
      {hint ? <BaseField.Description className="text-sm text-ink-muted">{hint}</BaseField.Description> : null}
      {required ? (
        <BaseField.Error match="valueMissing" className="text-sm text-bad">
          {TEXT.forms.required(label)}
        </BaseField.Error>
      ) : null}
      {error ? (
        <BaseField.Error match className="text-sm text-bad" role="alert">
          {error}
        </BaseField.Error>
      ) : null}
    </BaseField.Root>
  );
}

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-ui border border-line bg-surface p-5 shadow-ui">
      {title || actions ? (
        <header className="mb-3 flex items-center justify-between gap-4">
          {title ? <h2 className="text-xl font-semibold">{title}</h2> : <span />}
          {actions}
        </header>
      ) : null}
      {children}
    </section>
  );
}

const TONE = {
  neutral: "border-line text-ink-muted",
  caution: "border-caution text-caution",
  ok: "border-ok text-ok",
  bad: "border-bad text-bad",
} as const;

/** Status never relies on colour alone: the label is always written out (03/F12). */
export function Pill({ tone, children }: { tone: keyof typeof TONE; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-sm font-medium ${TONE[tone]}`}>
      {children}
    </span>
  );
}

export function Table({ caption, head, children }: { caption: string; head: string[]; children: ReactNode }) {
  return (
    <table className="w-full border-collapse text-left">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-line text-sm text-ink-muted">
          {head.map((h) => (
            <th key={h} scope="col" className="py-2 pr-4 font-medium">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

/** A panel that slides over the page for detail or a secondary task; focus is trapped and Escape closes it (03/F14). */
export function SidePanel({
  trigger,
  title,
  description,
  children,
}: {
  trigger: string;
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <BaseDialog.Root>
      <BaseDialog.Trigger className={buttonClass("secondary")}>{trigger}</BaseDialog.Trigger>
      <BaseDialog.Portal>
        <BaseDialog.Backdrop className="fixed inset-0 bg-ink/40" />
        <BaseDialog.Popup className="fixed inset-y-0 right-0 flex w-full max-w-md flex-col gap-4 overflow-y-auto border-l border-line bg-surface p-6 shadow-ui">
          <BaseDialog.Title className="text-xl font-semibold">{title}</BaseDialog.Title>
          {description ? (
            <BaseDialog.Description className="text-ink-muted">{description}</BaseDialog.Description>
          ) : null}
          <div className="flex-1">{children}</div>
          <div>
            <BaseDialog.Close className={buttonClass("secondary")}>{TEXT.ui.close}</BaseDialog.Close>
          </div>
        </BaseDialog.Popup>
      </BaseDialog.Portal>
    </BaseDialog.Root>
  );
}
