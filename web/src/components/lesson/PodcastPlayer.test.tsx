import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/en";
import { ApiError } from "@/lib/api";
import { journey, PODCAST_STALE_MS, podcastErrorKey, podcastStuck, type Podcast } from "@/lib/journey";

import { PodcastPlayer } from "./PodcastPlayer";

const show = (p: Podcast) => {
  vi.spyOn(journey, "podcast").mockResolvedValue(p);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><PodcastPlayer lessonId={7} lang="tanglish" /></QueryClientProvider>);
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("PodcastPlayer", () => {
  it("while it is being made: no button", async () => {
    show({ status: "generating", warmup: [], updated_at: new Date().toISOString(), stuck: false });
    expect(await screen.findByText(en.lj.podcast.making)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: en.common.retry })).toBeNull();
  });

  it("a stuck episode stops polling and offers Try again, which rebuilds it", async () => {
    show({ status: "generating", warmup: [], updated_at: new Date(Date.now() - PODCAST_STALE_MS - 1000).toISOString(), stuck: true });
    expect(await screen.findByText(en.lj.podcast.stuck)).toBeInTheDocument();
    const make = vi.spyOn(journey, "makePodcast").mockResolvedValue({ status: "generating", warmup: [], stuck: false });
    fireEvent.click(screen.getByRole("button", { name: en.common.retry }));
    await waitFor(() => expect(make).toHaveBeenCalledWith(7, "tanglish"));
    expect(await screen.findByText(en.lj.podcast.making)).toBeInTheDocument();
  });

  it("a failed episode shows the reason and Try again", async () => {
    show({ status: "failed", warmup: [], error: "provider_not_configured" });
    expect(await screen.findByRole("alert")).toHaveTextContent(en.lj.podcast.notConfigured);
    expect(screen.getByRole("button", { name: en.common.retry })).toBeInTheDocument();
  });

  it("maps API error codes from making an episode to clear messages", async () => {
    show({ status: "none", warmup: [] });
    vi.spyOn(journey, "makePodcast").mockRejectedValue(new ApiError(409, { code: "lesson_not_ready" }));
    fireEvent.click(await screen.findByRole("button", { name: en.lj.podcast.make }));
    expect(await screen.findByRole("alert")).toHaveTextContent(en.lj.podcast.notReady);
  });
});

describe("podcast helpers", () => {
  it("stuck = server flag, else older than 5 minutes; only while generating", () => {
    const now = Date.parse("2026-10-17T10:00:00Z");
    const old = new Date(now - PODCAST_STALE_MS).toISOString();
    expect(podcastStuck({ status: "generating", warmup: [], updated_at: old }, now)).toBe(true);
    expect(podcastStuck({ status: "generating", warmup: [], updated_at: new Date(now - 1000).toISOString() }, now)).toBe(false);
    expect(podcastStuck({ status: "generating", warmup: [], updated_at: old, stuck: false }, now)).toBe(false);
    expect(podcastStuck({ status: "ready", warmup: [], updated_at: old }, now)).toBe(false);
  });

  it("every known code has its own message", () => {
    expect(podcastErrorKey("podcast_budget")).toBe("lj.podcast.budget");
    expect(podcastErrorKey("bad_lang")).toBe("lj.podcast.badLang");
    expect(podcastErrorKey("generation_failed")).toBe("lj.podcast.failed");
    expect(podcastErrorKey(undefined)).toBe("lj.podcast.failed");
  });
});
