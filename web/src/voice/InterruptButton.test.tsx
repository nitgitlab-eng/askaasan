import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InterruptButton } from "./InterruptButton";
import type { useVoiceMode } from "./useVoiceMode";

type Voice = ReturnType<typeof useVoiceMode>;
const voice = (over: Partial<Voice>) => ({ active: true, state: "listening", interrupt: vi.fn(), ...over }) as unknown as Voice;

describe("InterruptButton", () => {
  it("shows only while the AI is answering by voice, and a tap interrupts it", () => {
    const v = voice({ state: "speaking" });
    render(<InterruptButton voice={v} busy={false} />);
    fireEvent.click(screen.getByRole("button", { name: /interrupt/i }));
    expect(v.interrupt).toHaveBeenCalled();
  });

  it("also shows while the reply is still coming (busy)", () => {
    render(<InterruptButton voice={voice({})} busy />);
    expect(screen.getByTestId("voice-interrupt")).toBeInTheDocument();
  });

  it("hidden when listening, or when voice is off", () => {
    const { rerender } = render(<InterruptButton voice={voice({})} busy={false} />);
    expect(screen.queryByTestId("voice-interrupt")).toBeNull();
    rerender(<InterruptButton voice={voice({ active: false, state: "speaking" })} busy />);
    expect(screen.queryByTestId("voice-interrupt")).toBeNull();
  });
});
