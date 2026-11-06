"use client";
// EXAMPLE SLICE: the brief panel on a work item, used by both web apps. It waits for the verified result (never
// optimistic, 03/F28), shows it through AIDraft, and says plainly when the assistant is off or unavailable (01/R5).
import { useState } from "react";

import { AIDraft, AIStatusBanner, type Citation } from "@/components/ai/ai";
import { Button, Card } from "@/components/ui/primitives";
import { ErrorState } from "@/components/ui/states";
import { AI_TEXT } from "@/lib/labels";

export type BriefResult = {
  status: string;
  abstention?: string | null;
  points: { text?: unknown; cite?: unknown }[];
};

type Props = {
  available: boolean;
  switchedOn: boolean;
  ask: () => Promise<{ brief?: BriefResult; error?: string }>;
};

export function BriefPanel({ available, switchedOn, ask }: Props) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ brief?: BriefResult; error?: string } | null>(null);
  const points = (result?.brief?.points ?? []).filter(
    (p): p is { text: string; cite: Citation } =>
      typeof p.text === "string" && typeof p.cite === "object" && p.cite !== null,
  );
  return (
    <Card title={AI_TEXT.brief.title}>
      <div className="flex flex-col gap-4">
        <AIStatusBanner switchedOn={switchedOn} available={available} />
        <div>
          <Button
            type="button"
            disabled={busy || !switchedOn}
            onClick={async () => {
              setBusy(true);
              setResult(await ask());
              setBusy(false);
            }}
          >
            {busy ? AI_TEXT.brief.asking : AI_TEXT.brief.ask}
          </Button>
        </div>
        {result?.error ? <ErrorState title={AI_TEXT.brief.title} body={result.error} /> : null}
        {result?.brief ? (
          <AIDraft
            status={result.brief.status}
            abstention={result.brief.abstention}
            citations={points.map((p) => p.cite)}
          >
            <ul className="list-disc pl-5">
              {points.map((p) => (
                <li key={`${p.cite.source}-${p.text}`}>{p.text}</li>
              ))}
            </ul>
          </AIDraft>
        ) : null}
      </div>
    </Card>
  );
}
