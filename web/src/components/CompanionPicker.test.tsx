import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { COMPANION_ART } from "@/mascot/art";
import { COMPANIONS, companionOf, isDefaultName } from "@/mascot/companions";
import { companionName } from "@/mascot/name";

import { CompanionPicker } from "./CompanionPicker";

const base = { character: "kili" as const, name: "Kili", color: "#22c55e", outfit: "none", accessories: [], position: "bottom-right" as const, chattiness: 2, enabled: true, voice: false };

describe("companion registry", () => {
  it("every registered companion has artwork, a name in both scripts and a colour", () => {
    for (const c of COMPANIONS) {
      expect(COMPANION_ART[c.id]).toBeTruthy();
      expect(c.name && c.tamil && c.emoji).toBeTruthy();
      expect(c.color).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it("unknown ids fall back to the default companion; default names are recognised in any script", () => {
    expect(companionOf("dragon").id).toBe("kili");
    expect(isDefaultName("யானை")).toBe(true);
    expect(isDefaultName("Mayil")).toBe(true);
    expect(isDefaultName("Chinnu")).toBe(false);
    expect(companionName("yaanai", "Kili", "ta")).toBe("யானை");
    expect(companionName("yaanai", "Chinnu", "ta")).toBe("Chinnu");
  });
});

describe("CompanionPicker (onboarding + Personalize)", () => {
  it("offers every companion in the registry", () => {
    render(<CompanionPicker prefs={base} onPick={() => {}} />);
    expect(screen.getAllByRole("radio")).toHaveLength(COMPANIONS.length);
    expect(screen.getByRole("radio", { checked: true })).toHaveTextContent(/kili/i);
  });

  it("picking Yaanai switches companion; a default name and colour follow it", () => {
    const onPick = vi.fn();
    render(<CompanionPicker prefs={base} onPick={onPick} />);
    fireEvent.click(screen.getByRole("radio", { name: /yaanai/i }));
    expect(onPick).toHaveBeenCalledWith({ character: "yaanai", color: "#8b9bb4", name: "Yaanai" });
  });

  it("a renamed companion keeps its name and a custom colour survives the switch", () => {
    const onPick = vi.fn();
    render(<CompanionPicker prefs={{ ...base, name: "Chinnu", color: "#f43f5e" }} onPick={onPick} />);
    fireEvent.click(screen.getByRole("radio", { name: /mayil/i }));
    expect(onPick).toHaveBeenCalledWith({ character: "mayil", color: "#f43f5e", name: "Chinnu" });
  });

  it("clicking the current companion does nothing", () => {
    const onPick = vi.fn();
    render(<CompanionPicker prefs={base} onPick={onPick} />);
    fireEvent.click(screen.getByRole("radio", { name: /kili/i }));
    expect(onPick).not.toHaveBeenCalled();
  });
});

describe("effective colour (what the learner actually sees)", () => {
  it("Kili's default green is drawn in the companion's own colour, and swatches lead with it", async () => {
    const { effectiveColor, swatchesFor } = await import("@/mascot/companions");
    expect(effectiveColor("yaanai", "#22c55e")).toBe("#8b9bb4");
    expect(effectiveColor("kili", "#22c55e")).toBe("#22c55e");
    expect(effectiveColor("mayil", "#f43f5e")).toBe("#f43f5e");
    expect(swatchesFor("yaanai", ["#22c55e", "#8b9bb4"])).toEqual(["#8b9bb4", "#22c55e"]);
  });

  it("an elephant still wearing Kili's green counts as its default colour, so switching gives the next companion its own", () => {
    const onPick = vi.fn();
    render(<CompanionPicker prefs={{ ...base, character: "yaanai", name: "Yaanai" }} onPick={onPick} />);
    fireEvent.click(screen.getByRole("radio", { name: /mayil/i }));
    expect(onPick).toHaveBeenCalledWith({ character: "mayil", color: "#2563eb", name: "Mayil" });
  });
});
