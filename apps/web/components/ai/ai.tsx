"use client";
// Shared AI screens for both web apps (03/F19–F21, F14, 04/H2, 01/R5). Presentational: data and actions arrive as
// props from each app's pages. The rules they hold: AI output is marked as AI-drafted with its sources one glance away;
// an abstention is shown as itself, never as agreement; no confidence number sits beside a judgement; a consequential
// action is deliberate (evidence beside the button, a reason to reject, one at a time, never optimistic); a switched
// off or unreachable assistant is always visible, and the rest of the product keeps working.
import { useRef, useState } from "react";

import { Button, Card, Field, Pill, Table } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import {
  AI_STATUS_LABELS,
  AI_TEXT,
  LOCALE,
  aiStatusLabel,
  labelled,
  proposalLabel,
  proposalTone,
  quoted,
} from "@/lib/labels";

export type Citation = { source: string; quote: string };

type StatusProps = { switchedOn: boolean; available: boolean };

/** Shown whenever the assistant is off or unreachable, so a degraded mode is never silent (01/R5). */
export function AIStatusBanner({ switchedOn, available }: StatusProps) {
  if (switchedOn && available) return null;
  return (
    <p role="status" className="rounded-ui border border-caution bg-surface px-4 py-3 text-ink">
      {switchedOn ? AI_TEXT.unavailable : AI_TEXT.off}
    </p>
  );
}

type DraftProps = {
  status: string; // the attempt's status: only "succeeded" shows a draft
  abstention?: string | null;
  citations?: Citation[];
  couldNotVerify?: string[];
  children?: React.ReactNode; // the step's own rendering of its verified result
};

/** An AI draft, or the honest reason there isn't one. Never shows a draft for anything but a verified result. */
export function AIDraft({ status, abstention, citations = [], couldNotVerify = [], children }: DraftProps) {
  if (status === "abstained") {
    return (
      <Card>
        <p className="font-medium">{AI_TEXT.abstained}</p>
        <p className="mt-1 text-ink-muted">{abstention}</p>
      </Card>
    );
  }
  if (status !== "succeeded") {
    return <ErrorState title={aiStatusLabel(status)} body={AI_TEXT.unavailable} />;
  }
  return (
    <Card>
      <p className="mb-3">
        <Pill tone="neutral">{AI_TEXT.drafted}</Pill>
      </p>
      <div className="max-w-prose">{children}</div>
      {citations.length > 0 ? (
        <details className="mt-4">
          <summary className="cursor-pointer font-medium">{AI_TEXT.sources}</summary>
          <ul className="mt-2 flex flex-col gap-2">
            {citations.map((c, i) => (
              <li key={`${c.source}-${i}`}>
                <blockquote className="border-l-2 border-line pl-3 text-ink-muted">{quoted(c.quote)}</blockquote>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {couldNotVerify.length > 0 ? (
        <div className="mt-4">
          <p className="font-medium">{AI_TEXT.couldNotVerify}</p>
          <ul className="list-disc pl-5 text-ink-muted">
            {couldNotVerify.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
}

export type ProposalView = {
  id: string;
  summary: string;
  status: string;
  version: number;
  evidence: Record<string, unknown>;
  decision_reason?: string | null;
};

type ProposalProps = {
  proposal: ProposalView;
  onDecide: (approve: boolean, reason: string) => Promise<void> | void;
  busy?: boolean;
  error?: string | null;
};

/** One proposal, decided on its own: evidence beside the buttons, a reason to reject, never optimistic (03/F20, F28). */
export function ProposalCard({ proposal, onDecide, busy = false, error = null }: ProposalProps) {
  const form = useRef<HTMLFormElement>(null);
  const [needsReason, setNeedsReason] = useState(false);
  const open = proposal.status === "proposed";
  const evidence = Object.entries(proposal.evidence).filter(([, v]) => typeof v === "string") as [string, string][];
  const reason = () => String(new FormData(form.current ?? undefined).get("reason") ?? "").trim();
  return (
    <Card
      title={proposal.summary}
      actions={<Pill tone={proposalTone(proposal.status)}>{proposalLabel(proposal.status)}</Pill>}
    >
      {evidence.length > 0 ? (
        <div className="mb-4">
          <p className="font-medium">{AI_TEXT.proposal.evidence}</p>
          <ul className="list-disc pl-5 text-ink-muted">
            {evidence.map(([k, v]) => (
              <li key={k}>{v}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {proposal.decision_reason ? <p className="mb-4 text-ink-muted">{proposal.decision_reason}</p> : null}
      {open ? (
        <form ref={form} className="flex flex-col gap-3" onSubmit={(e) => e.preventDefault()}>
          <Field
            label={AI_TEXT.proposal.reason}
            name="reason"
            multiline
            hint={AI_TEXT.proposal.reasonHint}
            error={needsReason ? AI_TEXT.proposal.reasonNeeded : undefined}
          />
          <div className="flex gap-3">
            <Button type="button" disabled={busy} onClick={() => void onDecide(true, reason())}>
              {AI_TEXT.proposal.approve}
            </Button>
            <Button
              type="button"
              variant="danger"
              disabled={busy}
              onClick={() => {
                if (!reason()) {
                  setNeedsReason(true);
                  return;
                }
                void onDecide(false, reason());
              }}
            >
              {AI_TEXT.proposal.reject}
            </Button>
          </div>
          {error ? (
            <p role="alert" className="text-bad">
              {error}
            </p>
          ) : null}
        </form>
      ) : null}
    </Card>
  );
}

type ListProps = {
  proposals: ProposalView[] | undefined;
  failed?: string | null;
  children: (p: ProposalView) => React.ReactNode;
};

/** Every data component ships empty, error and loading states (03/F14). */
export function ProposalList({ proposals, failed = null, children }: ListProps) {
  if (failed) return <ErrorState title={AI_STATUS_LABELS.failed} body={failed} />;
  if (proposals === undefined) return <LoadingState rows={2} label={AI_TEXT.proposal.noneOpen} />;
  if (proposals.length === 0)
    return <EmptyState title={AI_TEXT.proposal.noneOpen} body={AI_TEXT.proposal.noneOpenBody} />;
  return <div className="flex flex-col gap-4">{proposals.map(children)}</div>;
}

type FeedbackProps = { onSend: (verdict: "helpful" | "wrong" | "unsafe", correction: string) => Promise<void> | void };

/** Every correction becomes an eval candidate (06/E10). */
export function FeedbackControl({ onSend }: FeedbackProps) {
  const [sent, setSent] = useState(false);
  const [verdict, setVerdict] = useState<"helpful" | "wrong" | "unsafe" | null>(null);
  if (sent) return <p role="status">{AI_TEXT.feedback.thanks}</p>;
  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!verdict) return;
        const correction = String(new FormData(e.currentTarget).get("correction") ?? "");
        await onSend(verdict, correction);
        setSent(true);
      }}
    >
      <fieldset className="flex flex-wrap gap-3">
        <legend className="mb-2 font-medium">{AI_TEXT.feedback.question}</legend>
        {(["helpful", "wrong", "unsafe"] as const).map((v) => (
          <Button key={v} type="button" variant={verdict === v ? "primary" : "secondary"} onClick={() => setVerdict(v)}>
            {AI_TEXT.feedback[v]}
          </Button>
        ))}
      </fieldset>
      {verdict && verdict !== "helpful" ? (
        <Field label={AI_TEXT.feedback.correction} name="correction" multiline />
      ) : null}
      <div>
        <Button type="submit" disabled={!verdict}>
          {AI_TEXT.feedback.send}
        </Button>
      </div>
    </form>
  );
}

export type ShownItem = {
  context_id: string;
  source: string;
  trust: string;
  included: boolean;
  drop_reason?: string | null;
  text: string;
};

type InspectorProps = {
  status: string;
  shown: ShownItem[];
  said: string | null;
  model?: string | null;
  cost?: string | null;
};

const money = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "USD", maximumFractionDigits: 6 });

/** Why the assistant said this (04/X6): a detail view, so recorded identifiers may appear here (03/F16). */
export function AttemptInspector({ status, shown, said, model, cost }: InspectorProps) {
  return (
    <Card title={AI_TEXT.inspector.title}>
      <p className="mb-3">
        {[
          labelled(AI_TEXT.inspector.outcome, aiStatusLabel(status)),
          model ? labelled(AI_TEXT.inspector.model, model) : null,
          cost ? labelled(AI_TEXT.inspector.cost, money.format(Number(cost))) : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <Table caption={AI_TEXT.inspector.shown} head={[...AI_TEXT.inspector.head]}>
        {shown.map((s) => (
          <tr key={s.context_id} className="border-b border-line align-top">
            <td className="py-2 pr-4">{s.context_id}</td>
            <td className="py-2 pr-4">
              {s.source}
              {s.included ? null : ` (${AI_TEXT.inspector.dropped}: ${s.drop_reason})`}
            </td>
            <td className="py-2 pr-4 whitespace-pre-wrap">{s.text}</td>
          </tr>
        ))}
      </Table>
      <p className="mt-4 font-medium">{AI_TEXT.inspector.said}</p>
      <pre className="mt-1 max-w-full overflow-x-auto whitespace-pre-wrap rounded-ui border border-line p-3">
        {said ?? ""}
      </pre>
    </Card>
  );
}
