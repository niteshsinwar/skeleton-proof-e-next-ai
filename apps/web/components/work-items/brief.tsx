"use client";
// EXAMPLE SLICE: the Next.js side of the brief panel: the server action runs with the session and its CSRF token.
import { askForBrief } from "@/app/actions/brief";
import { BriefPanel } from "@/components/ai/brief-panel";

export function WorkItemBrief({
  id,
  csrf,
  available,
  switchedOn,
}: {
  id: string;
  csrf: string;
  available: boolean;
  switchedOn: boolean;
}) {
  return (
    <BriefPanel
      available={available}
      switchedOn={switchedOn}
      ask={async () => {
        const form = new FormData();
        form.set("id", id);
        form.set("csrf", csrf);
        return askForBrief({}, form);
      }}
    />
  );
}
