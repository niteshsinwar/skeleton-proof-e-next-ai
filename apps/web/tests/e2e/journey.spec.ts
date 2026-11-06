// The example slice end to end on the built artefact: sign in, create, submit, decide,
// and see the decision arrive live over SSE. A forced 422 keeps the user's input (03/F43).
import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

test("draft, submit, approve, and the owner sees the decision arrive live", async ({ browser }) => {
  const title = `Quarterly report ${Date.now()}`;
  const alice = await signIn(browser, "alice");
  await alice.getByLabel("Title").fill(title);
  await alice.getByRole("button", { name: "Create work item" }).click();
  await expect(alice.getByRole("heading", { level: 1, name: title })).toBeVisible();
  await alice.getByRole("button", { name: "Submit for a decision" }).click();
  await expect(alice.getByText("Sent for a decision")).toBeVisible(); // acknowledged at once (03/F44)
  await expect(alice.getByTestId("live-state")).toHaveText("Waiting for a decision");

  const bob = await signIn(browser, "bob");
  await expect(bob.getByText(/waiting for your decision/)).toBeVisible();
  await bob.getByRole("link", { name: title }).click();
  await bob.getByRole("button", { name: "Approve" }).click();
  await expect(bob.getByTestId("live-state")).toHaveText("Approved");

  // Alice's page never reloaded: the decision arrives over the event stream.
  await expect(alice.getByTestId("live-state")).toHaveText("Approved", { timeout: 15_000 });
});

test("a refused submission keeps what the user typed", async ({ browser }) => {
  const alice = await signIn(browser, "alice");
  const tooLong = "x".repeat(201); // the API's contract allows 200 characters, so it answers 422
  await alice.getByLabel("Title").fill(tooLong);
  await alice.getByRole("button", { name: "Create work item" }).click();
  // The error sits in the form itself: Next.js's route announcer is also an alert, so an unscoped check passes on it.
  const form = alice.getByRole("form", { name: "New work item" });
  await expect(form.getByRole("alert")).toBeVisible();
  await expect(form.getByLabel("Title")).toHaveValue(tooLong);
});

test("the approver can't decide their own item, and the screen offers no decision", async ({ browser }) => {
  const title = `Own item ${Date.now()}`;
  const bob = await signIn(browser, "bob");
  await bob.getByLabel("Title").fill(title);
  await bob.getByRole("button", { name: "Create work item" }).click();
  await expect(bob.getByRole("heading", { level: 1, name: title })).toBeVisible();
  await expect(bob.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
