// The session as the API sees it: who the caller is and what the grants allow, and ending it (02/Z4, Z5, 03/F40).
// Server-only: it carries the session's access token.
import { api } from "./transport";

export type Me = { subject: string; name: string | null; roles: string[]; capabilities: string[] };

/**
 * Who the API says the caller is, with what their grants allow on this call. Screens use it to offer only what will
 * be allowed: an affordance, never the control, since the API authorises every action (03/F9). Null when the API
 * can't say, so the screen offers nothing extra.
 */
export async function whoAmI(accessToken: string): Promise<Me | null> {
  try {
    const { data } = await api(accessToken).GET("/me", {});
    return data ?? null;
  } catch {
    return null;
  }
}

export function can(me: Me | null, capability: string): boolean {
  return me?.capabilities.includes(capability) ?? false;
}

type RevokeClient = {
  POST: (path: "/session/revoke", init: Record<string, unknown>) => Promise<{ response: Response }>;
};

/** True when the API no longer accepts this token: revoked now (204) or already unusable (401). */
export async function revokeSession(accessToken: string, client: RevokeClient = api(accessToken)): Promise<boolean> {
  try {
    const { response } = await client.POST("/session/revoke", {});
    return response.status === 204 || response.status === 401;
  } catch {
    return false;
  }
}
