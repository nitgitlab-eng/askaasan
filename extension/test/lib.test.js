/* Run from the repo root: node --test extension/test/*.test.js   (no dependencies) */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const A = require("../lib.js");

test("submitUrl keeps normal addresses unchanged", () => {
  const url = "https://docs.google.com/spreadsheets/d/1/edit?usp=sharing#gid=0";
  assert.equal(A.submitUrl(url), url);
});

test("submitUrl drops a huge query instead of failing with a generic error", () => {
  const url = `https://docs.google.com/spreadsheets/d/1/edit?state=${"x".repeat(5000)}#frag`;
  assert.equal(A.submitUrl(url), "https://docs.google.com/spreadsheets/d/1/edit");
});

test("submitUrl returns empty when even the path is too long, so the popup can say why", () => {
  assert.equal(A.submitUrl(`https://example.com/${"p".repeat(A.MAX_URL)}`), "");
  assert.equal(A.submitUrl(`not a url ${"x".repeat(A.MAX_URL)}`), "");
});

test("normalizeServer allows https and local http only", () => {
  assert.equal(A.normalizeServer("https://aasan.example.com/path"), "https://aasan.example.com");
  assert.equal(A.normalizeServer("http://localhost:5173"), "http://localhost:5173");
  assert.equal(A.normalizeServer("http://aasan.example.com"), "");
  assert.equal(A.normalizeServer("https://user:pw@aasan.example.com"), "");
});

test("retryAfterSeconds reads seconds or an HTTP date", () => {
  assert.equal(A.retryAfterSeconds("30"), 30);
  assert.equal(A.retryAfterSeconds(""), 0);
  assert.equal(A.retryAfterSeconds("Wed, 21 Oct 2026 07:28:30 GMT", Date.parse("Wed, 21 Oct 2026 07:28:00 GMT")), 30);
  assert.equal(A.retryAfterSeconds("soon"), 0);
});

test("pairing_busy says how long to wait", () => {
  assert.equal(A.pairingBusyText(new A.ApiError(429, { code: "pairing_busy" }, 42)), "Too many pairing attempts right now — try again in 42 seconds.");
  assert.equal(A.pairingBusyText(new A.ApiError(429, { code: "pairing_busy" }, 1)), "Too many pairing attempts right now — try again in 1 second.");
  assert.match(A.pairingBusyText(new A.ApiError(429, { code: "pairing_busy" })), /try again in a minute/);
  assert.equal(A.pairingBusyText(new A.ApiError(429, { code: "grading_budget_exceeded" }, 5)), "");
});

test("call() passes Retry-After from a 429 into the error", async () => {
  global.chrome = { storage: { local: { get: async () => ({}), remove: async () => {} } } };
  global.fetch = async () => ({ ok: false, status: 429, json: async () => ({ code: "pairing_busy" }), headers: { get: (h) => (h === "Retry-After" ? "17" : null) } });
  await assert.rejects(A.call("/api/ext/pair/claim/", { method: "POST", body: { code: "123456" }, token: "" }), (e) => {
    assert.equal(e.retryAfter, 17);
    assert.equal(A.pairingBusyText(e), "Too many pairing attempts right now — try again in 17 seconds.");
    return true;
  });
  delete global.fetch;
  delete global.chrome;
});

test("the default server is the live site, over https", () => {
  assert.equal(A.DEFAULT_SERVER, "https://askaasan.com");
  assert.equal(A.normalizeServer(A.DEFAULT_SERVER), "https://askaasan.com");
});
