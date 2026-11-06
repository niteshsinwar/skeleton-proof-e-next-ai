"use client";
// Warns before the session ends and offers to sign in again in a new window, so this page and anything typed
// into it stay as they are (03/F40). The new window tells this page when it is done (SESSION_CHANNEL).
import { useEffect, useState } from "react";

import { SESSION_TEXT } from "@/lib/labels";
import { SESSION_CHANNEL, nextCheckIn, sessionPhase, type RenewedMessage } from "@/lib/session-timing";

export function SessionNotice({ expiresAt: initial }: { expiresAt: number }) {
  const [expiresAt, setExpiresAt] = useState(initial);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const delay = nextCheckIn(now, expiresAt);
    if (delay === null) return;
    const timer = setTimeout(() => setNow(Date.now()), delay);
    return () => clearTimeout(timer);
  }, [now, expiresAt]);

  useEffect(() => {
    if (typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(SESSION_CHANNEL);
    channel.onmessage = (event: MessageEvent<RenewedMessage>) => {
      if (event.data?.type === "renewed" && Number.isFinite(event.data.expiresAt)) {
        setExpiresAt(event.data.expiresAt);
        setNow(Date.now());
      }
    };
    return () => channel.close();
  }, []);

  const phase = sessionPhase(now, expiresAt);
  if (phase === "ok") return null;
  const minutes = Math.max(1, Math.ceil((expiresAt * 1000 - now) / 60_000));
  return (
    <div role="status" className="border-b border-caution bg-surface">
      <p className="mx-auto flex max-w-5xl flex-wrap items-center gap-3 px-6 py-2 text-sm">
        <span>{phase === "warn" ? SESSION_TEXT.endsIn(minutes) : SESSION_TEXT.ended}</span>
        <a href="/auth/login?popup=1" target="_blank" rel="noopener" className="font-medium text-accent underline">
          {SESSION_TEXT.signInAgain}
        </a>
      </p>
    </div>
  );
}
