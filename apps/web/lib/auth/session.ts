// Sessions live in an encrypted, httpOnly cookie: tokens are never reachable from JavaScript (03/F9).
// Server-only: import from server components, route handlers and server actions, never from client components.
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { env } from "@/lib/env";

export type Session = {
  sub: string;
  name: string;
  accessToken: string;
  exp: number; // seconds since epoch
  csrf: string; // double-submit token for sensitive actions (03/F39)
  accountSession?: string; // our own accounts only: the account server's session, ended at sign-out
};

export const SESSION_COOKIE = "session";
export const TX_COOKIE = "oidc_tx";

const enc = new TextEncoder();
const dec = new TextDecoder();

function b64url(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64url");
}

async function key(secret: string): Promise<CryptoKey> {
  if (secret.length < 32) {
    // Fail closed (02/B7): without a real secret there are no sessions at all.
    throw new Error("SESSION_SECRET must be set to at least 32 characters");
  }
  const digest = await crypto.subtle.digest("SHA-256", enc.encode(secret));
  return crypto.subtle.importKey("raw", digest, "AES-GCM", false, ["encrypt", "decrypt"]);
}

export async function seal(value: unknown, secret: string = env().SESSION_SECRET): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv },
    await key(secret),
    enc.encode(JSON.stringify(value)),
  );
  return `${b64url(iv)}.${b64url(new Uint8Array(data))}`;
}

export async function unseal<T>(sealed: string | undefined, secret: string = env().SESSION_SECRET): Promise<T | null> {
  if (!sealed) return null;
  const [iv, data] = sealed.split(".");
  if (!iv || !data) return null;
  const k = await key(secret);
  try {
    const plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: Buffer.from(iv, "base64url") },
      k,
      Buffer.from(data, "base64url"),
    );
    return JSON.parse(dec.decode(plain)) as T;
  } catch {
    return null; // tampered or from another key: treated as no session
  }
}

export function cookieOptions(maxAgeSeconds: number) {
  return { httpOnly: true, secure: true, sameSite: "lax" as const, path: "/", maxAge: maxAgeSeconds };
}

// The cookie outlives the token by this much so a re-login can carry the CSRF token over; getSession still refuses
// an expired session, so the extra time grants nothing.
export const RENEW_GRACE_SECONDS = 3600;

/** The session after a sign-in. The same person signing in again keeps their CSRF token, so forms already on
 * screen still submit (03/F40). */
export function startSession(previous: Session | null, signedIn: Omit<Session, "csrf">): Session {
  return { ...signedIn, csrf: previous?.sub === signedIn.sub ? previous.csrf : crypto.randomUUID() };
}

export async function getSession(): Promise<Session | null> {
  const session = await unseal<Session>((await cookies()).get(SESSION_COOKIE)?.value);
  if (!session || session.exp * 1000 <= Date.now()) return null;
  return session;
}

/** Every page, route and action that needs a user calls this; nothing relies on a proxy check alone (03/F40). */
export async function requireSession(): Promise<Session> {
  const session = await getSession();
  if (!session) redirect("/auth/login");
  return session;
}

export function verifyCsrf(session: Session, submitted: FormDataEntryValue | null): boolean {
  return typeof submitted === "string" && submitted.length > 0 && submitted === session.csrf;
}
