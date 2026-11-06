import "@/styles/globals.css";

import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import type { ReactNode } from "react";

import { Providers } from "@/components/providers";
import { LOCALE, TEXT } from "@/lib/labels";

export const metadata: Metadata = { title: TEXT.appName, description: TEXT.appDescription };

// The theme is chosen on the server and written before first paint: no inline script, no flash (03/F11).
// proxy.ts made this request's CSP nonce; the providers hand it to anything that renders an inline tag (03/F38).
export default async function RootLayout({ children }: { children: ReactNode }) {
  const theme = (await cookies()).get("theme")?.value === "dark" ? "dark" : "light";
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang={LOCALE} data-theme={theme}>
      <body>
        <Providers nonce={nonce}>{children}</Providers>
      </body>
    </html>
  );
}
