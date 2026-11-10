/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { defineConfig, type Connect, type Plugin } from "vite";

/** The page CSP nginx sends for /pyodide/ (infra/nginx/pyodide-headers.conf); mirrored here so dev and preview match. */
const PYODIDE_CSP =
  "sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'";

/**
 * Self-hosted Pyodide for code activities (no CDN in the site CSP). Copies the runtime the runner needs from the
 * `pyodide` npm package into public/pyodide/v<version>/ (gitignored), so Vite serves it in dev and copies it into
 * dist on build. The runner only runs plain Python (stdlib, no loadPackage), so no wheels are copied.
 * In dev/preview it also adds the headers nginx sets: CORS (the sandboxed frame has an opaque origin) and the CSP.
 */
function selfHostPyodide(): Plugin {
  const FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"];
  const headers: Connect.NextHandleFunction = (req, res, next) => {
    if (req.url?.startsWith("/pyodide/")) {
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Content-Security-Policy", PYODIDE_CSP);
    }
    next();
  };
  return {
    name: "self-host-pyodide",
    buildStart() {
      const pkg = dirname(createRequire(import.meta.url).resolve("pyodide/package.json"));
      const { version } = JSON.parse(readFileSync(join(pkg, "package.json"), "utf8")) as { version: string };
      const root = join(import.meta.dirname, "public", "pyodide");
      if (!readFileSync(join(root, "runner.html"), "utf8").includes(`src="v${version}/pyodide.js"`))
        throw new Error(`public/pyodide/runner.html must load v${version}/pyodide.js (the installed pyodide version)`);
      for (const d of readdirSync(root)) if (/^v\d/.test(d) && d !== `v${version}`) rmSync(join(root, d), { recursive: true });
      const out = join(root, `v${version}`);
      mkdirSync(out, { recursive: true });
      for (const f of FILES) copyFileSync(join(pkg, f), join(out, f));
    },
    configureServer: (server) => void server.middlewares.use(headers),
    configurePreviewServer: (server) => void server.middlewares.use(headers),
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), selfHostPyodide()],
  resolve: { alias: { "@": "/src" } },
  build: {
    // The only chunks over 500 kB are lazy single libraries (elk 1.46 MB, mermaid parser, Avatar3D, cytoscape) that load
    // just on the diagram / 3D screens; the entry chunk is ~145 kB. Warn only if something grows past elk.
    chunkSizeWarningLimit: 1500,
    rolldownOptions: {
      output: {
        // Long-lived vendor chunks: the app code changes often, these rarely do (better caching, smaller entry chunk).
        // Heavy libraries (mermaid + elk + cytoscape, three, KaTeX) stay out of these groups: they load only on the screens that use them.
        codeSplitting: {
          groups: [
            { name: "vendor-react", test: /node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@tanstack)[\\/]/ },
            { name: "vendor-motion", test: /node_modules[\\/](motion|motion-dom|motion-utils|framer-motion)[\\/]/ },
            { name: "vendor-i18n", test: /node_modules[\\/](i18next|react-i18next)[\\/]/ },
            { name: "strings", test: /src[\\/]i18n[\\/](en|ta)\.ts$/ }, // English + Tamil interface text (other languages load on demand)
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
