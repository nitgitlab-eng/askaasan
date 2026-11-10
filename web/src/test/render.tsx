import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { DialogHost } from "@/components/dialog";

/** Renders a page inside the app's providers: a fresh query cache, a router at `route`, and the dialog host. */
export function renderPage(ui: ReactElement, { route = "/", path = "*" }: { route?: string; path?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <DialogHost />
        <Routes>
          <Route path={path} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Routes mocked `api()` calls by path prefix; unknown paths reject so missing mocks show up. */
type Init = { method?: string; json?: unknown };
type Handler = (init?: Init) => unknown;

export function apiRoutes(table: Record<string, Handler | object | null>) {
  return async (path: string, init?: Init) => {
    const key = typeof path === "string" ? Object.keys(table).sort((a, b) => b.length - a.length).find((k) => path.startsWith(k)) : undefined;
    if (key === undefined) throw new Error(`unmocked ${path}`);
    const v = table[key];
    return typeof v === "function" ? (v as Handler)(init) : v;
  };
}
