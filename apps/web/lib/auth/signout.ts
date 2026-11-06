// Signing out (02/Z4, 03/F40): the session's token is revoked on the API before the cookie goes, so the token
// stops working at once. If the API can't be reached the cookie still goes, and the user is told the server
// side didn't finish, so nothing looks more finished than it is (README #12).
import type { Session } from "./session";

export async function signOut(
  session: Session | null,
  revoke: (accessToken: string) => Promise<boolean>,
): Promise<{ redirectTo: string }> {
  if (!session) return { redirectTo: "/" };
  return { redirectTo: (await revoke(session.accessToken)) ? "/" : "/?signout=incomplete" };
}
