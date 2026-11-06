"use client";
// Shown in the window used to sign in again: tells the page that asked, then tries to close itself (03/F40).
import { useEffect } from "react";

import { SESSION_TEXT } from "@/lib/labels";
import { SESSION_CHANNEL, type RenewedMessage } from "@/lib/session-timing";

export function Renewed({ expiresAt }: { expiresAt: number }) {
  useEffect(() => {
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(SESSION_CHANNEL);
      channel.postMessage({ type: "renewed", expiresAt } satisfies RenewedMessage);
      channel.close();
    }
    window.close(); // allowed only for some windows; the text below covers the rest
  }, [expiresAt]);
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <h1 className="text-xl font-semibold">{SESSION_TEXT.renewedTitle}</h1>
      <p className="measure text-ink-muted">{SESSION_TEXT.renewedBody}</p>
    </main>
  );
}
