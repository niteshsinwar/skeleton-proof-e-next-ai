// Chrome: header, navigation, sign-out, and the journey indicator (03/F2, F18).
import Link from "next/link";
import type { ReactNode } from "react";

import { SessionNotice } from "@/components/shell/session-notice";
import { Button } from "@/components/ui/primitives";
import { TEXT } from "@/lib/labels";

export function Shell({
  user,
  csrf,
  expiresAt,
  children,
}: {
  user: string;
  csrf: string;
  expiresAt: number;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <SessionNotice expiresAt={expiresAt} />
      <header className="border-b border-line bg-surface">
        <nav
          aria-label={TEXT.shell.nav}
          className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-6 py-3"
        >
          <Link href="/work-items" className="text-lg font-semibold">
            {TEXT.appName}
          </Link>
          <form action="/auth/logout" method="post" className="flex items-center gap-3">
            <span className="text-sm text-ink-muted">{TEXT.shell.signedInAs(user)}</span>
            <input type="hidden" name="csrf" value={csrf} />
            <Button type="submit" variant="secondary">
              {TEXT.shell.signOut}
            </Button>
          </form>
        </nav>
      </header>
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">{children}</main>
    </div>
  );
}
