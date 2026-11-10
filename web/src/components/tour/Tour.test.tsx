import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import { TourHost } from "./Tour";
import { useTour } from "./tourStore";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => null) }));

afterEach(() => {
  act(() => useTour.getState().set(null));
  document.body.querySelectorAll("[data-tour]").forEach((e) => e.remove());
  vi.restoreAllMocks();
});

describe("Creator Lab tour spotlight (R30)", () => {
  it("follows its target when the page scrolls", async () => {
    const target = document.createElement("button");
    target.dataset.tour = "lab-new";
    document.body.appendChild(target);
    vi.spyOn(target, "offsetParent", "get").mockReturnValue(document.body); // jsdom has no layout
    let top = 300;
    vi.spyOn(target, "getBoundingClientRect").mockImplementation(() => ({ top, left: 20, width: 100, height: 40, bottom: top + 40, right: 120, x: 20, y: top, toJSON: () => ({}) }) as DOMRect);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => { cb(0); return 1; });

    renderPage(<TourHost />);
    act(() => useTour.getState().set("lab", 1));
    const ring = () => document.querySelector<HTMLElement>(".ring-accent")!;
    expect(ring().style.top).toBe("294px"); // 300 - 6px padding

    top = 120; // the page scrolled up by 180px
    act(() => void window.dispatchEvent(new Event("scroll")));
    expect(ring().style.top).toBe("114px");

    top = 80; // a scrolling panel moved (scroll events don't bubble; capture catches them)
    act(() => void document.body.dispatchEvent(new Event("scroll")));
    expect(ring().style.top).toBe("74px");
  });
});

describe("the tour never silently blocks the page", () => {
  it("a click on the dimmed page closes the tour and reaches what was clicked (e.g. the Ask Aasan box)", async () => {
    const ask = document.createElement("button");
    ask.textContent = "Ask";
    const clicked = vi.fn();
    ask.addEventListener("click", clicked);
    document.body.appendChild(ask);
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => { cb(0); return 1; });
    document.elementFromPoint = vi.fn(() => ask);

    renderPage(<TourHost />);
    act(() => useTour.getState().set("lab", 0));
    const dialog = await screen.findByRole("dialog");
    act(() => void fireEvent.pointerDown(dialog, { clientX: 40, clientY: 300 }));
    expect(useTour.getState().name).toBeNull();
    expect(clicked).toHaveBeenCalledTimes(1);
    ask.remove();
  });

  it("clicks inside the tour card don't close it", async () => {
    renderPage(<TourHost />);
    act(() => useTour.getState().set("lab", 0));
    const next = await screen.findByRole("button", { name: /next/i });
    act(() => void fireEvent.pointerDown(next));
    expect(useTour.getState().name).toBe("lab");
  });
});
