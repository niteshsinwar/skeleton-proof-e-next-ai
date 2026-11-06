// Every data component ships empty, error and loading states (03/F14); status always carries words (03/F12).
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { SessionNotice } from "@/components/shell/session-notice";
import { Journey } from "@/components/shell/journey";
import { Field, Pill } from "@/components/ui/primitives";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";

afterEach(cleanup); // vitest runs without globals, so Testing Library does not clean up on its own

describe("states", () => {
  it("renders empty, error and loading with the right roles", () => {
    render(
      <>
        <EmptyState title="Nothing yet" body="What this is and the first step." />
        <ErrorState title="Couldn't load" body="Try again." />
        <LoadingState rows={2} label="Loading items" />
      </>,
    );
    expect(screen.getByRole("alert").textContent).toContain("Couldn't load");
    expect(screen.getByRole("status", { name: "Loading items" })).toBeTruthy();
    expect(screen.getByText("Nothing yet")).toBeTruthy();
  });

  it("status pills always have a text label", () => {
    render(<Pill tone="ok">Approved</Pill>);
    expect(screen.getByText("Approved")).toBeTruthy();
  });

  it("a field with an error shows it beside a visible label", () => {
    render(<Field label="Title" name="title" error="Use at most 200 characters." defaultValue="kept input" />);
    expect(screen.getByText("Title")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Use at most 200 characters.");
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("kept input");
  });

  it("a required field is checked when the user leaves it, not on each keystroke (03/F43)", async () => {
    render(<Field label="Title" name="title" required />);
    const user = userEvent.setup();
    const input = screen.getByRole("textbox");
    await user.type(input, "a");
    await user.clear(input);
    expect(screen.queryByText("Title is needed to continue.")).toBeNull(); // still in the field: no error yet
    await user.tab();
    expect(await screen.findByText("Title is needed to continue.")).toBeTruthy();
    expect(input.getAttribute("aria-invalid")).toBe("true");
  });

  it("the journey says 'stage n of m', never a percentage", () => {
    render(<Journey state="submitted" />);
    expect(screen.getByText(/Stage 2 of 3/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/%/);
  });
});

describe("session notice (03/F40)", () => {
  const inSeconds = (s: number) => Math.floor(Date.now() / 1000) + s;

  it("stays silent while the session has time left", () => {
    render(<SessionNotice expiresAt={inSeconds(3600)} />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("warns before expiry with a way to sign in again that keeps this page", () => {
    render(<SessionNotice expiresAt={inSeconds(60)} />);
    const notice = screen.getByRole("status");
    expect(notice.textContent).toMatch(/ends in/i);
    const link = screen.getByRole("link", { name: /sign in again/i });
    expect(link.getAttribute("target")).toBe("_blank"); // a new window, so this page and its form input stay
    expect(link.getAttribute("href")).toBe("/auth/login?popup=1");
  });

  it("says plainly when the session has ended, keeping the page", () => {
    render(<SessionNotice expiresAt={inSeconds(-5)} />);
    expect(screen.getByRole("status").textContent).toMatch(/has ended/i);
  });
});
