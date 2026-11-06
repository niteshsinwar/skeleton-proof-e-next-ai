// The living component catalogue (03/F52): every primitive in every state, checked by e2e + axe. Shared by both
// web apps; each mounts it only when the catalogue is switched on, so it never ships as a public page. Its words are
// samples that show each primitive, not product copy, so it is exempt from the labels rule by name.
import { AICatalogue } from "@/components/ai/catalogue-ai";
import { Journey } from "@/components/shell/journey";
import { Button, Card, Field, Pill, SidePanel, Table } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { ToastExample } from "@/components/ui/toast";
import { WORK_ITEM_STATES, stateLabel, stateTone } from "@/lib/labels";

export function Catalogue() {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-6 py-10">
      <h1 className="text-2xl font-semibold">Component catalogue</h1>
      <Card title="Buttons">
        <div className="flex flex-wrap gap-3">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="danger">Danger</Button>
          <Button disabled>Disabled</Button>
        </div>
      </Card>
      <Card title="Fields">
        <div className="flex max-w-md flex-col gap-4">
          <Field label="Title" name="example-title" hint="A short sentence." />
          <Field label="Title with an error" name="example-error" defaultValue="x" error="Say what to do to fix it." />
          <Field label="Reason" name="example-reason" multiline />
          <Field
            label="Required"
            name="example-required"
            required
            hint="Leave it empty and move on to see the check."
          />
        </div>
      </Card>
      <Card title="Status">
        <div className="flex flex-wrap gap-3">
          {WORK_ITEM_STATES.map((s) => (
            <Pill key={s} tone={stateTone(s)}>
              {stateLabel(s)}
            </Pill>
          ))}
        </div>
      </Card>
      <Card title="Journey">
        <Journey state="submitted" />
      </Card>
      <Card title="Table">
        <Table caption="Example rows" head={["Title", "Status"]}>
          <tr className="border-b border-line">
            <td className="py-3 pr-4">Fix the gate</td>
            <td className="py-3 pr-4">
              <Pill tone="caution">{stateLabel("submitted")}</Pill>
            </td>
          </tr>
        </Table>
      </Card>
      <Card title="Side panel and toast">
        <div className="flex flex-wrap gap-3">
          <SidePanel
            trigger="Open the side panel"
            title="Details"
            description="Detail or a secondary task, over the page."
          >
            <p>Focus stays inside until it closes; Escape closes it.</p>
          </SidePanel>
          <ToastExample label="Show a toast" title="Saved" description="Your change is in place." />
        </div>
      </Card>
      <Card title="Empty, error and loading states">
        <div className="flex flex-col gap-4">
          <EmptyState title="Nothing yet" body="What this is, and the first action to take." />
          <ErrorState title="Couldn't load" body="What happened, and what to do next." />
          <LoadingState rows={2} />
        </div>
      </Card>
      <AICatalogue />
    </main>
  );
}
