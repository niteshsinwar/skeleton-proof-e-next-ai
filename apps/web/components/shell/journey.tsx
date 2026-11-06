// Where an item is in its journey (03/F18), shared by both web apps.
import { JOURNEY, TEXT, type WorkItemState } from "@/lib/labels";

/** "Stage 2 of 3", never a fake percentage (03/F18). */
export function Journey({ state }: { state: WorkItemState }) {
  const position = state === "rejected" ? 1 : JOURNEY.findIndex((s) => s.state === state);
  return (
    <ol aria-label={TEXT.shell.progress} className="flex flex-wrap gap-2 text-sm">
      {JOURNEY.map((step, i) => (
        <li
          key={step.state}
          aria-current={i === position ? "step" : undefined}
          className={`rounded-full border px-3 py-1 ${i === position ? "border-accent font-semibold text-accent" : "border-line text-ink-muted"}`}
        >
          {TEXT.shell.stage(i + 1, JOURNEY.length, step.label)}
        </li>
      ))}
    </ol>
  );
}
