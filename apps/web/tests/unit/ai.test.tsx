// The shared AI screens' rules (03/F19–F21, F14, F28, 01/R5, 06/E10). Failure replays: an abstention shown as
// agreement (04 §8); a consequential action that needs no reason or runs optimistically (03/F20, F28).
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AIDraft,
  AIStatusBanner,
  AttemptInspector,
  FeedbackControl,
  ProposalCard,
  ProposalList,
} from "@/components/ai/ai";
import { AI_TEXT } from "@/lib/labels";

afterEach(cleanup);

const PROPOSAL = {
  id: "p1",
  summary: "Add a note",
  status: "proposed",
  version: 1,
  evidence: { why: "Asked for it." },
};

describe("AI drafts", () => {
  it("marks a verified draft as AI-drafted and keeps its sources one glance away", () => {
    render(
      <AIDraft status="succeeded" citations={[{ source: "c1", quote: "approved by finance" }]}>
        <p>Approved.</p>
      </AIDraft>,
    );
    expect(screen.getByText(AI_TEXT.drafted)).toBeTruthy();
    expect(screen.getByText(/approved by finance/)).toBeTruthy();
  });

  it("shows an abstention as an abstention, never as a draft or agreement", () => {
    render(<AIDraft status="abstained" abstention="The record has no amount." />);
    expect(screen.getByText(AI_TEXT.abstained)).toBeTruthy();
    expect(screen.getByText("The record has no amount.")).toBeTruthy();
    expect(screen.queryByText(AI_TEXT.drafted)).toBeNull();
  });

  it("shows no draft for an answer that was rejected or never came", () => {
    render(<AIDraft status="invalid">Should not appear</AIDraft>);
    expect(screen.queryByText("Should not appear")).toBeNull();
    expect(screen.getByRole("alert")).toBeTruthy();
  });

  it("says when the assistant is off, and says nothing when it is on", () => {
    const { rerender } = render(<AIStatusBanner switchedOn={false} available={true} />);
    expect(screen.getByRole("status").textContent).toBe(AI_TEXT.off);
    rerender(<AIStatusBanner switchedOn={true} available={true} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("proposals", () => {
  it("needs a reason to reject, and does not send without one", async () => {
    const decide = vi.fn();
    render(<ProposalCard proposal={PROPOSAL} onDecide={decide} />);
    await userEvent.click(screen.getByRole("button", { name: AI_TEXT.proposal.reject }));
    expect(decide).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain(AI_TEXT.proposal.reasonNeeded);
    await userEvent.type(screen.getByRole("textbox"), "Not needed");
    await userEvent.click(screen.getByRole("button", { name: AI_TEXT.proposal.reject }));
    expect(decide).toHaveBeenCalledWith(false, "Not needed");
  });

  it("approves one proposal at a time, with its evidence beside the button", async () => {
    const decide = vi.fn();
    render(<ProposalCard proposal={PROPOSAL} onDecide={decide} />);
    expect(screen.getByText("Asked for it.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: AI_TEXT.proposal.approve }));
    expect(decide).toHaveBeenCalledWith(true, "");
  });

  it("offers no decision once a proposal is decided", () => {
    render(<ProposalCard proposal={{ ...PROPOSAL, status: "executed" }} onDecide={vi.fn()} />);
    expect(screen.queryByRole("button", { name: AI_TEXT.proposal.approve })).toBeNull();
  });

  it("has empty, error and loading states", () => {
    const { rerender } = render(<ProposalList proposals={[]}>{() => null}</ProposalList>);
    expect(screen.getByText(AI_TEXT.proposal.noneOpen)).toBeTruthy();
    rerender(<ProposalList proposals={undefined}>{() => null}</ProposalList>);
    expect(screen.getByRole("status")).toBeTruthy();
    rerender(
      <ProposalList proposals={[]} failed="It broke.">
        {() => null}
      </ProposalList>,
    );
    expect(screen.getByRole("alert").textContent).toContain("It broke.");
  });
});

describe("feedback and inspection", () => {
  it("sends a verdict with its correction once, then thanks the person", async () => {
    const send = vi.fn();
    render(<FeedbackControl onSend={send} />);
    await userEvent.click(screen.getByRole("button", { name: AI_TEXT.feedback.wrong }));
    await userEvent.type(screen.getByRole("textbox"), "It was rejected.");
    await userEvent.click(screen.getByRole("button", { name: AI_TEXT.feedback.send }));
    expect(send).toHaveBeenCalledWith("wrong", "It was rejected.");
    expect(screen.getByRole("status").textContent).toBe(AI_TEXT.feedback.thanks);
  });

  it("shows what was shown, what was left out and why, and what was said", () => {
    render(
      <AttemptInspector
        status="succeeded"
        shown={[
          { context_id: "c1", source: "record.details", trust: "record", included: true, text: "Approved." },
          {
            context_id: "c2",
            source: "record.secret",
            trust: "record",
            included: false,
            drop_reason: "not_in_grounding",
            text: "x",
          },
        ]}
        said='{"summary": "ok"}'
      />,
    );
    expect(screen.getByText(/not_in_grounding/)).toBeTruthy();
    expect(screen.getByText('{"summary": "ok"}')).toBeTruthy();
  });
});
