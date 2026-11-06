// Sign out: POST only, with the CSRF token (03/F39). The session's token is revoked on the API first, so it stops
// working at once (02/Z4, 03/F40); then the cookie is destroyed.
import { NextResponse, type NextRequest } from "next/server";

import { revokeSession } from "@/lib/api/session";
import { SESSION_COOKIE, getSession, verifyCsrf } from "@/lib/auth/session";
import { signOut } from "@/lib/auth/signout";
import { baseUrl } from "@/lib/env";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const session = await getSession();
  const form = await request.formData();
  if (session && !verifyCsrf(session, form.get("csrf"))) {
    return new NextResponse("Invalid request", { status: 403 });
  }
  const { redirectTo } = await signOut(session, (token) => revokeSession(token));
  if (redirectTo !== "/") console.error(JSON.stringify({ event: "session.revoke_failed", sub: session?.sub }));
  const response = NextResponse.redirect(new URL(redirectTo, baseUrl()), { status: 303 });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
