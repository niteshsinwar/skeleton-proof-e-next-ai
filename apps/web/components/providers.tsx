"use client";

import { CSPProvider } from "@base-ui/react/csp-provider";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useReportWebVitals } from "next/web-vitals";
import { useState, type ReactNode } from "react";

import { ErrorReporting } from "@/components/error-reporting";
import { ToastProvider, ToastViewport } from "@/components/ui/toast";

/** Field Core Web Vitals go to our own endpoint (03/F26): p75 comes from real users, not the lab. No PII. */
function WebVitals() {
  useReportWebVitals((metric) => {
    const body = JSON.stringify({
      name: metric.name,
      value: metric.value,
      rating: metric.rating,
      path: window.location.pathname,
    });
    navigator.sendBeacon?.("/api/vitals", body);
  });
  return null;
}

/** `nonce` is this request's CSP nonce: Base UI puts it on any inline style or script it renders (03/F38). */
export function Providers({ nonce, children }: { nonce?: string; children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } }));
  return (
    <CSPProvider nonce={nonce}>
      <QueryClientProvider client={client}>
        <ToastProvider>
          <WebVitals />
          <ErrorReporting />
          {children}
          <ToastViewport />
        </ToastProvider>
      </QueryClientProvider>
    </CSPProvider>
  );
}
