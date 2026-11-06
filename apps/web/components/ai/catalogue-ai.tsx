"use client";
// The AI components in the catalogue (03/F52). A client component, because its samples pass handlers, which a server
// component may not hand to a client one. Sample words, not product copy, so it is exempt from the labels rule by name.
import { Card } from "@/components/ui/primitives";

import { AIDraft, AIStatusBanner, AttemptInspector, FeedbackControl, ProposalCard, ProposalList } from "./ai";

const SAMPLE_PROPOSAL = {
  id: "p1",
  summary: "Add a note to the record",
  status: "proposed",
  version: 1,
  evidence: { why: "The approver asked for it." },
};

export function AICatalogue() {
  return (
    <Card title="Assistant">
      <div className="flex flex-col gap-4">
        <AIStatusBanner switchedOn={false} available={true} />
        <AIDraft status="succeeded" citations={[{ source: "c1", quote: "approved by finance on 3 November" }]}>
          <p>The invoice was approved by finance.</p>
        </AIDraft>
        <AIDraft status="abstained" abstention="The record does not say who approved it." />
        <AIDraft status="failed" />
        <ProposalCard proposal={SAMPLE_PROPOSAL} onDecide={() => undefined} />
        <ProposalList proposals={[]}>{() => null}</ProposalList>
        <FeedbackControl onSend={() => undefined} />
        <AttemptInspector
          status="succeeded"
          shown={[
            {
              context_id: "c1",
              source: "record.details",
              trust: "record",
              included: true,
              text: "Approved by finance.",
            },
          ]}
          said='{"summary": "Approved."}'
          model="example-model"
          cost="0.0021"
        />
      </div>
    </Card>
  );
}
