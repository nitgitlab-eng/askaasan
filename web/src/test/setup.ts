import "@testing-library/jest-dom/vitest";
import "@/i18n";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup()); // vitest runs without globals, so Testing Library can't register this itself

// jsdom has no layout: scrolling is a no-op in tests.
Element.prototype.scrollTo ??= () => {};
Element.prototype.scrollIntoView ??= () => {};
