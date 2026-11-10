// Writes src/i18n/locales/en.json from en.ts — the source for machine-translated interface languages.
// Usage: node scripts/export-i18n.mjs   (Node ≥ 22.6 strips the TypeScript types itself)
import { writeFileSync } from "node:fs";

const en = (await import("../src/i18n/en.ts")).default;
writeFileSync(new URL("../src/i18n/locales/en.json", import.meta.url), JSON.stringify(en, null, 1) + "\n");
console.log("wrote src/i18n/locales/en.json");
