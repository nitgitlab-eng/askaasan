import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { confirmDialog, promptDialog } from "@/lib/dialog";

import { DialogHost } from "./dialog";

describe("app dialogs (R25)", () => {
  it("confirm resolves false on Cancel and true on OK", async () => {
    render(<DialogHost />);
    let p!: Promise<boolean>;
    act(() => void (p = confirmDialog("Delete it?")));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(await p).toBe(false);
    act(() => void (p = confirmDialog("Delete it?")));
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));
    expect(await p).toBe(true);
  });

  it("prompt returns the typed text, or null on Escape", async () => {
    render(<DialogHost />);
    let p!: Promise<string | null>;
    act(() => void (p = promptDialog("Lesson title", { defaultValue: "Intro" })));
    expect(await screen.findByRole("dialog", { name: "Lesson title" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  Loops  " } });
    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await p).toBe("Loops");
    act(() => void (p = promptDialog("Lesson title")));
    await screen.findByRole("dialog");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(await p).toBeNull();
  });
});
