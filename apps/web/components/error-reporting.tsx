"use client";
// Shared by both web apps (03/F48).
import { useEffect } from "react";

import { reportClientError } from "@/lib/telemetry";

/** Script errors, unhandled rejections and failed resource loads are reported, never swallowed (03/F48). */
export function ErrorReporting() {
  useEffect(() => {
    const onError = (event: Event) => {
      if (event instanceof ErrorEvent) return reportClientError("error", event.message);
      const target = event.target;
      if (target instanceof HTMLElement)
        reportClientError("resource", `${target.tagName.toLowerCase()} failed to load`);
    };
    const onRejection = (event: PromiseRejectionEvent) =>
      reportClientError(
        "unhandledrejection",
        event.reason instanceof Error ? event.reason.message : "non-error rejection",
      );
    window.addEventListener("error", onError, true); // capture: failed resource loads don't bubble
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError, true);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
