"use client";
// Toasts acknowledge a finished action at once (03/F14, F44). They never hold the only copy of an error:
// failures stay beside the form that caused them (03/F43), so a missed toast loses nothing.
import { Toast } from "@base-ui/react/toast";

import { buttonClass } from "@/components/ui/primitives";
import { TEXT } from "@/lib/labels";

export const ToastProvider = Toast.Provider;
export const useToasts = Toast.useToastManager;

export function ToastViewport() {
  const { toasts } = Toast.useToastManager();
  return (
    <Toast.Portal>
      <Toast.Viewport className="fixed right-4 bottom-4 z-50 flex w-full max-w-sm flex-col gap-2">
        {toasts.map((toast) => (
          <Toast.Root key={toast.id} toast={toast} className="rounded-ui border border-line bg-surface p-4 shadow-ui">
            <Toast.Content className="flex items-start gap-3">
              <div className="flex flex-1 flex-col gap-1">
                <Toast.Title className="font-medium" />
                <Toast.Description className="text-sm text-ink-muted" />
              </div>
              <Toast.Close className={buttonClass("secondary")}>{TEXT.ui.dismiss}</Toast.Close>
            </Toast.Content>
          </Toast.Root>
        ))}
      </Toast.Viewport>
    </Toast.Portal>
  );
}

/** A button that raises an example toast, for the catalogue; its words are the catalogue's samples. */
export function ToastExample({ label, title, description }: { label: string; title: string; description: string }) {
  const toasts = useToasts();
  return (
    <button type="button" className={buttonClass("secondary")} onClick={() => toasts.add({ title, description })}>
      {label}
    </button>
  );
}
