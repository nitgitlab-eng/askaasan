import { describe, expect, it } from "vitest";

import en from "./en";
import enJson from "./locales/en.json";
import ta from "./ta";

/** Flattens nested strings to dotted keys; arrays count as one key each, like i18next's returnObjects lookups. */
function keys(o: unknown, prefix = ""): string[] {
  if (typeof o !== "object" || o === null || Array.isArray(o)) return [prefix];
  return Object.entries(o).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k));
}

const json = import.meta.glob<{ default: unknown }>(["./locales/*.json", "!./locales/en.json"], { eager: true });
const want = new Set(keys(en));

function drift(locale: unknown) {
  const have = new Set(keys(locale));
  return { missing: [...want].filter((k) => !have.has(k)), extra: [...have].filter((k) => !want.has(k)) };
}

describe("locale drift (R71)", () => {
  it("locales/en.json matches en.ts (run `node scripts/export-i18n.mjs` after editing en.ts)", () => {
    expect(drift(enJson)).toEqual({ missing: [], extra: [] });
  });

  it("ta.ts has exactly the English keys", () => {
    expect(drift(ta)).toEqual({ missing: [], extra: [] });
  });

  it.each(Object.entries(json).map(([path, mod]) => [path.replace("./locales/", ""), mod.default]))("%s has exactly the English keys", (_name, locale) => {
    expect(drift(locale)).toEqual({ missing: [], extra: [] });
  });
});
