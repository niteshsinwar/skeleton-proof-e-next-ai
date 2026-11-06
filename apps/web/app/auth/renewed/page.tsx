// The end of a sign-in started from the session notice (03/F40): no navigation chrome, just the hand-back.
import { Renewed } from "@/components/shell/renewed";
import { requireSession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

export default async function RenewedPage() {
  const session = await requireSession();
  return <Renewed expiresAt={session.exp} />;
}
