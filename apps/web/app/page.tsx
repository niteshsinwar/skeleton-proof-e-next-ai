import Link from "next/link";
import { redirect } from "next/navigation";

import { getSession } from "@/lib/auth/session";
import { SESSION_TEXT, TEXT } from "@/lib/labels";

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ signin?: string; signout?: string }> }) {
  if (await getSession()) redirect("/work-items");
  const { signin, signout } = await searchParams;
  return (
    <main className="mx-auto flex max-w-xl flex-col gap-6 px-6 py-16">
      <h1 className="text-2xl font-semibold">{TEXT.appName}</h1>
      <p className="measure text-ink-muted">{TEXT.home.intro}</p>
      {signin && TEXT.home.signinProblem[signin] ? (
        <p role="alert" className="text-bad">
          {TEXT.home.signinProblem[signin]}
        </p>
      ) : null}
      {signout === "incomplete" ? (
        <p role="alert" className="text-caution">
          {SESSION_TEXT.signoutIncomplete}
        </p>
      ) : null}
      <div>
        <Link
          href="/auth/login"
          prefetch={false}
          className="inline-flex min-h-11 items-center rounded-ui bg-accent px-4 font-medium text-accent-ink"
        >
          {TEXT.home.signIn}
        </Link>
      </div>
    </main>
  );
}
