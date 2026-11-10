/* Run from the repo root: node --test extension/test/*.test.js   (no dependencies) */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const S = require("../steps.js");

const task = {
  id: 7, title: "Budget sheet",
  observe: { steps: [
    { id: "s1", label: "Open Sheets", url_pattern: "https://docs.google.com/spreadsheets/*", text: "" },
    { id: "s2", label: "Show the total", url_pattern: "https://*.google.com/spreadsheets/d/*/edit*", text: "Total" },
  ] },
};

test("urlMatches mirrors the server rules", () => {
  const cases = [
    ["https://docs.google.com/spreadsheets/d/1/edit", "https://docs.google.com/spreadsheets/*", true],
    ["https://docs.google.com/document/d/1", "https://docs.google.com/spreadsheets/*", false],
    ["https://a.docs.google.com/spreadsheets/x", "https://*.google.com/spreadsheets/*", true],
    ["https://google.com/spreadsheets/x", "https://*.google.com/spreadsheets/*", true],
    ["https://evil-google.com/spreadsheets/x", "https://*.google.com/spreadsheets/*", false],
    ["https://evil.com/x.google.com/spreadsheets/", "https://*.google.com/*", false],
    ["https://docs.google.com.evil.com/", "https://docs.google.com/*", false],
    ["http://docs.google.com/", "https://docs.google.com/*", false],
    ["https://u:p@docs.google.com/", "https://docs.google.com/*", false],
    ["https://docs.google.com:8443/", "https://docs.google.com/*", false],
    ["https://DOCS.google.com/a#frag", "https://docs.google.com/a", true],
    ["https://chatgpt.com/c/1?q=hello", "https://chatgpt.com/c/*", true], // query ignored
    ["https://chatgpt.com/?q=hello", "https://chatgpt.com?q=*", false], // queries aren't allowed in patterns
    ["https://evil.com\\x.google.com/a", "https://*.google.com/*", false],
    ["https://docs.google.com/a b", "https://docs.google.com/*", false],
    ["https://a.foo.co.in/x", "https://*.foo.co.in/*", true],
    ["https://chatgpt.com/anything", "https://chatgpt.com", true],
    ["javascript:alert(1)", "https://chatgpt.com", false],
    ["https://x.com/a.b", "https://x.com/a?b", false], // only * is a wildcard
  ];
  for (const [url, pattern, ok] of cases) assert.equal(S.urlMatches(url, pattern), ok, `${url} vs ${pattern}`);
});

test("invalid patterns never match and never yield permissions", () => {
  for (const p of ["https://*/*", "https://*.com/*", "https://a*.com/*", "http://a.com/*", "https://localhost/*", "<all_urls>", ""]) {
    assert.equal(S.splitPattern(p), null, p);
    assert.deepEqual(S.originsOf([{ url_pattern: p }]), []);
  }
});

test("permission origins are exactly the steps' hosts", () => {
  const w = S.newWatch(task);
  assert.deepEqual(w.hosts, ["docs.google.com", "*.google.com"]);
  assert.deepEqual(w.origins, ["https://docs.google.com/*", "https://*.google.com/*"]);
  assert.equal(S.newWatch({ id: 1, observe: null }), null);
  assert.equal(S.hostAllowed("https://mail.google.com/", w.hosts), true);
  assert.equal(S.hostAllowed("https://example.com/", w.hosts), false);
  assert.equal(S.hostAllowed("http://docs.google.com/", w.hosts), false);
});

test("advance ticks steps in order and waits for text", async () => {
  let w = S.newWatch(task);
  const calls = [];
  const has = (found) => async (text) => { calls.push(text); return found; };
  // a page that matches step 2 first does nothing: steps go in order
  let r = await S.advance(w, { url: "https://docs.google.com/spreadsheets/d/x/edit", title: "x" }, has(true));
  assert.equal(r.watch.observed.length, 2); // s1 (/spreadsheets/*) and s2 both match this page
  // fresh watch: other site → untouched, no page check
  w = S.newWatch(task);
  r = await S.advance(w, { url: "https://example.com/spreadsheets/", title: "x" }, has(true));
  assert.equal(r.changed, false);
  assert.deepEqual(calls, ["Total"]);
  // step 1 page, then step 2 page without the text → waiting on s2
  r = await S.advance(w, { url: "https://docs.google.com/spreadsheets/u/0/", title: "Sheets" }, has(false));
  assert.deepEqual(r.watch.observed.map((o) => o.step), ["s1"]);
  assert.equal(w.observed.length, 0, "input not mutated");
  r = await S.advance(r.watch, { url: "https://docs.google.com/spreadsheets/d/abc/edit", title: "Budget" }, has(false));
  assert.equal(r.watch.waiting, "s2");
  assert.equal(S.isDone(r.watch), false);
  // text appears → done; a throwing check counts as "not found"
  const thrower = await S.advance(r.watch, { url: "https://docs.google.com/spreadsheets/d/abc/edit" }, async () => { throw new Error("x"); });
  assert.equal(S.isDone(thrower.watch), false);
  r = await S.advance(r.watch, { url: "https://docs.google.com/spreadsheets/d/abc/edit", title: "Budget" }, has(true));
  assert.equal(S.isDone(r.watch), true);
  assert.equal(r.watch.waiting, "");
  const ev = S.evidence(r.watch);
  assert.deepEqual(ev.map((e) => [e.step, e.text_found]), [["s1", null], ["s2", true]]);
  assert.deepEqual(Object.keys(ev[0]).sort(), ["step", "text_found", "title", "url"]); // no page content, ever
  assert.equal(S.nextStep(r.watch), null);
});

test("hasText must return exactly true", async () => {
  const w = S.newWatch(task);
  const r1 = await S.advance(w, { url: "https://docs.google.com/spreadsheets/u/0/" }, async () => true);
  const r2 = await S.advance(r1.watch, { url: "https://docs.google.com/spreadsheets/d/a/edit" }, async () => "Total found");
  assert.equal(r2.watch.observed.length, 1);
});

test("wildcards over public suffixes or bare TLDs are refused", () => {
  for (const sfx of ["co.in", "net.in", "ac.in", "gov.in", "co.uk", "com.au", "github.io", "gitlab.io", "blogspot.com", "netlify.app",
                     "vercel.app", "pages.dev", "web.app", "herokuapp.com", "appspot.com", "CO.IN", "in", "io"]) {
    assert.equal(S.splitPattern(`https://*.${sfx}/*`), null, sfx);
  }
  assert.deepEqual(S.splitPattern("https://*.myschool.co.in/*"), ["*.myschool.co.in", "/*"]);
  assert.deepEqual(S.splitPattern("https://github.io/x"), ["github.io", "/x"]); // an exact host is fine
});

test("public suffix list matches the shared JSON (and the API copy)", () => {
  const ext = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "public_suffixes.json"), "utf8"));
  const api = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "api", "apps", "extension", "public_suffixes.json"), "utf8"));
  assert.deepEqual([...S.PUBLIC_SUFFIXES].sort(), [...ext.suffixes].sort());
  assert.deepEqual(ext, api);
});

test("evidence has no query, fragment or credentials; titles capped", async () => {
  assert.equal(S.stripUrl("https://u:p@Docs.google.com/a/b?token=1#f"), "https://docs.google.com/a/b");
  assert.equal(S.stripUrl("https://evil.com\\x.google.com/"), "");
  const w = S.newWatch(task);
  let r = await S.advance(w, { url: "https://docs.google.com/spreadsheets/u/0/?token=SECRET#x", title: "T".repeat(500) }, async () => true);
  r = await S.advance(r.watch, { url: "https://docs.google.com/spreadsheets/d/a/edit?usp=SECRET", title: "B" }, async () => true);
  const ev = S.evidence(r.watch);
  assert.deepEqual(ev.map((e) => e.url), ["https://docs.google.com/spreadsheets/u/0/", "https://docs.google.com/spreadsheets/d/a/edit"]);
  assert.equal(ev[0].title.length, 120);
  assert.ok(!JSON.stringify(ev).includes("SECRET"));
});
