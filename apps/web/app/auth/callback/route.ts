// Finish the code flow: exchange the code (PKCE, state and nonce checked), then keep the tokens server-side.
import { NextResponse, type NextRequest } from "next/server";
import * as client from "openid-client";

import { oidcConfig } from "@/lib/auth/oidc";
import {
  RENEW_GRACE_SECONDS,
  SESSION_COOKIE,
  TX_COOKIE,
  cookieOptions,
  seal,
  startSession,
  unseal,
  type Session,
} from "@/lib/auth/session";
import { baseUrl } from "@/lib/env";

export const dynamic = "force-dynamic";

type Tx = { verifier: string; state: string; nonce: string; popup?: boolean };

export async function GET(request: NextRequest) {
  const tx = await unseal<Tx>(request.cookies.get(TX_COOKIE)?.value);
  if (!tx) return NextResponse.redirect(new URL("/?signin=expired", baseUrl()));
  const config = await oidcConfig();
  // Rebuild the callback URL from the configured base, not from Host headers an attacker could set.
  const current = new URL(`${request.nextUrl.pathname}${request.nextUrl.search}`, baseUrl());
  let tokens;
  try {
    tokens = await client.authorizationCodeGrant(config, current, {
      pkceCodeVerifier: tx.verifier,
      expectedState: tx.state,
      expectedNonce: tx.nonce,
      idTokenExpected: true,
    });
  } catch {
    return NextResponse.redirect(new URL("/?signin=failed", baseUrl()));
  }
  const claims = tokens.claims();
  if (!claims) return NextResponse.redirect(new URL("/?signin=failed", baseUrl()));
  const expiresIn = tokens.expiresIn() ?? 900;
  const previous = await unseal<Session>(request.cookies.get(SESSION_COOKIE)?.value);
  const sub = String(claims.sub);
  const session = startSession(previous, {
    sub,
    name: typeof claims.name === "string" ? claims.name : sub,
    accessToken: tokens.access_token,
    exp: Math.floor(Date.now() / 1000) + expiresIn,
  });
  const response = NextResponse.redirect(new URL(tx.popup ? "/auth/renewed" : "/work-items", baseUrl()));
  response.cookies.set(SESSION_COOKIE, await seal(session), cookieOptions(expiresIn + RENEW_GRACE_SECONDS));
  response.cookies.delete(TX_COOKIE);
  return response;
}
