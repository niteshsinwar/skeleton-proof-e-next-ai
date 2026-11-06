// OIDC authorization code + PKCE in the Next.js server (backend-for-frontend, 02/Z2, 13/SK4).
// The browser never sees a token; the API verifies every token it receives (02/Z1).
import * as client from "openid-client";

import { env } from "@/lib/env";

/** Plain-HTTP issuers are accepted only on loopback (the local mock issuer); everything else must be HTTPS. */
export function isLoopbackIssuer(issuer: string): boolean {
  const url = new URL(issuer);
  return url.protocol === "http:" && (url.hostname === "127.0.0.1" || url.hostname === "localhost");
}

let config: Promise<client.Configuration> | null = null;

export function oidcConfig(): Promise<client.Configuration> {
  const { OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET } = env();
  config ??= client.discovery(
    new URL(OIDC_ISSUER),
    OIDC_CLIENT_ID,
    OIDC_CLIENT_SECRET,
    undefined,
    isLoopbackIssuer(OIDC_ISSUER) ? { execute: [client.allowInsecureRequests] } : undefined,
  );
  return config;
}

export function redirectUri(): string {
  return `${env().APP_BASE_URL}/auth/callback`;
}
