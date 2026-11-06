import type { ReactNode } from "react";

import { Shell } from "@/components/shell/shell";
import { requireSession } from "@/lib/auth/session";
import { personLabel } from "@/lib/labels";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const session = await requireSession();
  return (
    <Shell user={personLabel(session.name, session.sub)} csrf={session.csrf} expiresAt={session.exp}>
      {children}
    </Shell>
  );
}
