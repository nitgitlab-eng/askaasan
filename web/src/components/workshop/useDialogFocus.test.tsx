import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { useDialogFocus } from "./useDialogFocus";

function Panel({ onClose }: { onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useDialogFocus(ref, onClose);
  return (
    <div ref={ref} role="dialog" aria-modal="true" aria-label="Drawer">
      <button type="button">First</button>
      <button type="button">Last</button>
    </div>
  );
}

function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open</button>
      {open && <Panel onClose={() => { onClose(); setOpen(false); }} />}
      {/* Stands in for the app's confirm dialog, opened from inside the drawer. */}
      <div role="dialog" aria-modal="true" aria-label="Confirm"><button type="button">OK</button></div>
    </>
  );
}

describe("useDialogFocus", () => {
  it("focuses the first control, wraps Tab both ways, closes on Escape and restores focus", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    const opener = screen.getByRole("button", { name: "Open" });
    opener.focus();
    fireEvent.click(opener);
    const first = screen.getByRole("button", { name: "First" });
    const last = screen.getByRole("button", { name: "Last" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(opener).toHaveFocus();
  });

  it("leaves keys alone while focus is in another modal (a confirm opened from the drawer)", () => {
    const onClose = vi.fn();
    render(<Harness onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    const ok = screen.getByRole("button", { name: "OK" });
    ok.focus();
    fireEvent.keyDown(window, { key: "Tab" });
    expect(ok).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });
});
