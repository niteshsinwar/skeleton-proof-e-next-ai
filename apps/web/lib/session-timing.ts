// When to warn before a session expires (03/F40). Pure, so it is unit-tested; safe in client components.

/** The notice appears this long before the session ends. */
export const WARN_BEFORE_MS = 120_000;

export type SessionPhase = "ok" | "warn" | "ended";

export function sessionPhase(nowMs: number, expiresAtSeconds: number): SessionPhase {
  const left = expiresAtSeconds * 1000 - nowMs;
  if (left <= 0) return "ended";
  return left <= WARN_BEFORE_MS ? "warn" : "ok";
}

/** Milliseconds until the notice next needs to change, or null once the session has ended. */
export function nextCheckIn(nowMs: number, expiresAtSeconds: number): number | null {
  const left = expiresAtSeconds * 1000 - nowMs;
  if (left <= 0) return null;
  return left > WARN_BEFORE_MS ? left - WARN_BEFORE_MS : Math.min(1_000, left);
}

/** The channel a re-login in another window uses to tell this page the session was renewed. */
export const SESSION_CHANNEL = "session";
export type RenewedMessage = { type: "renewed"; expiresAt: number };
