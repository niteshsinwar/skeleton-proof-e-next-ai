import Link from "next/link";

import { EmptyState } from "@/components/ui/states";
import { TEXT } from "@/lib/labels";

export default function NotFound() {
  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <EmptyState
        title={TEXT.errors.notFound}
        body={TEXT.errors.notFoundBody}
        action={
          <Link href="/" className="text-accent underline">
            {TEXT.errors.toStart}
          </Link>
        }
      />
    </main>
  );
}
