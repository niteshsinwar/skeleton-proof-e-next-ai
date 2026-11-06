// Every on-screen word for a domain identifier goes through here (03/F16): no raw ids, codes or
// engineering vocabulary reach a screen. Roles change defaults and permissions, never vocabulary (02/Z12).

/** The one place the locale is set; dates and numbers format through Intl with it (03/F55). */
export const LOCALE = "en-GB";

export const WORK_ITEM_STATES = ["draft", "submitted", "approved", "rejected"] as const;
export type WorkItemState = (typeof WORK_ITEM_STATES)[number];

export const STATE_LABELS: Record<WorkItemState, string> = {
  draft: "Draft",
  submitted: "Waiting for a decision",
  approved: "Approved",
  rejected: "Returned",
};

// Judgement tone is a separate scale from identity colour, and always travels with a text label (03/F12).
export const STATE_TONE: Record<WorkItemState, "neutral" | "caution" | "ok" | "bad"> = {
  draft: "neutral",
  submitted: "caution",
  approved: "ok",
  rejected: "bad",
};

export const JOURNEY: { state: WorkItemState; label: string }[] = [
  { state: "draft", label: "Write it" },
  { state: "submitted", label: "Decision" },
  { state: "approved", label: "Done" },
];

export function stateLabel(state: string): string {
  return (STATE_LABELS as Record<string, string>)[state] ?? "Unknown";
}

export function stateTone(state: string): "neutral" | "caution" | "ok" | "bad" {
  return (STATE_TONE as Record<string, "neutral" | "caution" | "ok" | "bad">)[state] ?? "neutral";
}

/**
 * People are shown by name, never by subject identifier (03/F16). The API sends the name a person had when they
 * acted; one whose sign-in carried no name is "Unknown person", and no subject at all means nobody yet.
 */
export function personLabel(name: string | null | undefined, subject: string | null | undefined): string {
  if (!subject) return "Nobody yet";
  return name?.trim() || "Unknown person";
}

export function whenLabel(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  return date.toDateString() === now.toDateString()
    ? `Today, ${date.toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" })}`
    : date.toLocaleDateString(LOCALE, { day: "numeric", month: "short", year: "numeric" });
}

/** Words about the session: the expiry notice and the re-login hand-back (03/F40). */
export const SESSION_TEXT = {
  endsIn: (minutes: number) =>
    `Your session ends in ${minutes} ${minutes === 1 ? "minute" : "minutes"}. Anything you've typed stays on this page.`,
  ended: "Your session has ended. Anything you've typed stays on this page; sign in again to save it.",
  signInAgain: "Sign in again (opens a new window)",
  renewedTitle: "You're signed in again",
  renewedBody: "Go back to your other window to carry on. You can close this one.",
  signoutIncomplete:
    "You're signed out on this device, but the server couldn't confirm it. If this is a shared computer, sign in and out again.",
} as const;

/**
 * Every other word on screen, grouped by where it appears (03/F55). Copy changes here, never in a component;
 * ESLint's react/jsx-no-literals and a source test refuse new inline strings, so a second language is a new
 * copy of this module rather than a hunt through the components.
 */
export const TEXT = {
  appName: "Work items",
  appDescription: "Draft work, send it for a decision, and see who holds it.",
  signInFirst: "Sign in first.",
  home: {
    intro: "Draft something that needs a decision, submit it, and someone else approves or returns it.",
    signIn: "Sign in",
    signinProblem: {
      expired: "That sign-in took too long. Please try again.",
      failed: "Sign-in didn't complete. Please try again.",
    } as Record<string, string>,
  },
  shell: {
    nav: "Main",
    signedInAs: (name: string) => `Signed in as ${name}`,
    signOut: "Sign out",
    progress: "Progress",
    stage: (n: number, of: number, label: string) => `Stage ${n} of ${of}: ${label}`,
  },
  list: {
    title: "Work items",
    newItem: "New work item",
    all: "All work items",
    mine: "Your work items",
    loadFailed: "Couldn't load the list",
    loadFailedBody: (problem: string) => `${problem} Reload to try again.`,
    loadFailedFallback: "The list could not be loaded.",
    empty: "No work items yet",
    emptyBody: "A work item is something you want decided. Create one above, then submit it for a decision.",
    caption: "Work items",
    columns: ["Title", "Status", "Owner", "Created"],
    more: "Show more",
  },
  item: {
    back: "Back to work items",
    loadFailed: "Couldn't load this item",
    loadFailedBody: "Reload to try again.",
    details: "Details",
    owner: "Owner",
    created: "Created",
    decidedBy: "Decided by",
    reason: "Reason",
    nextStep: "Next step",
    yourDecision: "Your decision",
  },
  forms: {
    title: "Title",
    titleHint: "A short sentence someone else will understand.",
    create: "Create work item",
    creating: "Creating…",
    working: "Working…",
    reason: "Reason",
    required: (label: string) => `${label} is needed to continue.`,
    command: { submit: "Submit for a decision", approve: "Approve", reject: "Return with a reason" },
    done: { submit: "Sent for a decision", approve: "Approved", reject: "Returned to the author" },
    otherUser: "Someone else signed in from this browser; reload the page.",
    stale: "This form is out of date; reload the page and try again.",
    unexpected: "Something went wrong; your input is kept below. Try again.",
  },
  live: {
    checking: "Checking for decisions…",
    checkFailed: "Couldn't check for decisions.",
    nothingWaiting: "Nothing is waiting for you.",
    waiting: (count: number) => `${count} waiting for your decision`,
  },
  errors: {
    title: "Something went wrong",
    body: "This page could not be shown. Try again; if it keeps happening, tell us what you were doing.",
    tryAgain: "Try again",
    notFound: "Nothing here",
    notFoundBody: "This page does not exist, or you do not have access to it.",
    toStart: "Go to the start",
  },
  ui: { close: "Close", dismiss: "Dismiss" },
} as const;

// The product AI's words (03/F16, F19): outcomes in plain language; an abstention never reads as agreement, and no
// confidence number is ever shown beside a judgement.
export const AI_STATUS_LABELS = {
  succeeded: "Drafted by the assistant",
  abstained: "The assistant couldn't answer",
  invalid: "The assistant's answer was rejected",
  refused: "The assistant declined",
  failed: "The assistant is unavailable",
} as const;

export function aiStatusLabel(s: string): string {
  return (AI_STATUS_LABELS as Record<string, string>)[s] ?? AI_STATUS_LABELS.failed;
}

/** A quotation, with the typographic marks kept out of the components. */
export function quoted(text: string): string {
  return `“${text}”`;
}

/** "Label: value", the one way a labelled fact is written on screen. */
export function labelled(label: string, value: string): string {
  return `${label}: ${value}`;
}

export const PROPOSAL_STATUSES = ["proposed", "approved", "rejected", "executed", "failed"] as const;
export type ProposalState = (typeof PROPOSAL_STATUSES)[number];

export const PROPOSAL_LABELS: Record<ProposalState, string> = {
  proposed: "Waiting for your decision",
  approved: "Approved, running",
  rejected: "Rejected",
  executed: "Done",
  failed: "Couldn't be done",
};

export const PROPOSAL_TONE: Record<ProposalState, "neutral" | "caution" | "ok" | "bad"> = {
  proposed: "caution",
  approved: "neutral",
  rejected: "neutral",
  executed: "ok",
  failed: "bad",
};

export const AI_TEXT = {
  drafted: "Drafted by the assistant. Check it before you rely on it.",
  sources: "Where this comes from",
  couldNotVerify: "What it couldn't check",
  abstained: "The assistant couldn't answer this:",
  off: "The assistant is switched off here for now. Everything else works as usual.",
  unavailable: "The assistant can't be reached right now. Everything else works as usual.",
  proposal: {
    evidence: "Why it was proposed",
    approve: "Approve",
    reject: "Reject",
    reason: "Reason",
    reasonHint: "Say why, so the next person knows.",
    reasonNeeded: "Give a reason to reject it.",
    noneOpen: "Nothing is waiting for a decision.",
    noneOpenBody: "When the assistant proposes a change, it appears here for someone to approve or reject.",
  },
  feedback: {
    question: "Was this answer right?",
    helpful: "It was right",
    wrong: "It was wrong",
    unsafe: "It was harmful",
    correction: "What should it have said?",
    send: "Send",
    thanks: "Thank you. A person reviews every report.",
  },
  brief: {
    title: "Ask the assistant",
    ask: "Brief me on this item",
    asking: "Briefing…",
  },
  inspector: {
    title: "Why the assistant said this",
    shown: "What it was shown",
    said: "What it said",
    dropped: "Left out",
    outcome: "Outcome",
    model: "Model",
    cost: "Cost",
    head: ["Block", "Source", "Text"],
  },
} as const;

export function proposalLabel(s: string): string {
  return (PROPOSAL_LABELS as Record<string, string>)[s] ?? s;
}

export function proposalTone(s: string): "neutral" | "caution" | "ok" | "bad" {
  return (PROPOSAL_TONE as Record<string, "neutral" | "caution" | "ok" | "bad">)[s] ?? "neutral";
}
