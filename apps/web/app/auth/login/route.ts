// Start the authorization code flow with PKCE, state and nonce (02/Z2). The verifier never leaves the server.
import { NextResponse, type NextRequest } from "next/server";
import * as client from "openid-client";

import { oidcConfig, redirectUri } from "@/lib/auth/oidc";
import { TX_COOKIE, cookieOptions, seal } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const config = await oidcConfig();
  const verifier = client.randomPKCECodeVerifier();
  const state = client.randomState();
  const nonce = client.randomNonce();
  const params: Record<string, string> = {
    redirect_uri: redirectUri(),
    scope: "openid profile",
    code_challenge: await client.calculatePKCECodeChallenge(verifier),
    code_challenge_method: "S256",
    state,
    nonce,
  };
  const hint = request.nextUrl.searchParams.get("hint");
  if (hint && /^[a-z0-9._-]{1,64}$/i.test(hint)) params.login_hint = hint;
  const response = NextResponse.redirect(client.buildAuthorizationUrl(config, params));
  const popup = request.nextUrl.searchParams.get("popup") === "1"; // started from the session notice (03/F40)
  response.cookies.set(TX_COOKIE, await seal({ verifier, state, nonce, popup }), cookieOptions(300));
  return response;
}
