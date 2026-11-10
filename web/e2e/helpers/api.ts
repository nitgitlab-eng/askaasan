import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { request, type APIRequestContext, type APIResponse } from "@playwright/test";

import { API_URL } from "./env";

export interface TestUser {
  email: string;
  password: string;
  name: string;
  id: number;
  access: string;
  refresh: string;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function uniqueEmail(tag = "u") {
  return `e2e-${tag}-${Date.now().toString(36)}-${randomBytes(3).toString("hex")}@example.com`;
}

export const strongPassword = () => `E2e!${randomBytes(9).toString("base64url")}`;

/** The refresh token arrives only as the HttpOnly `aasan_refresh` cookie. */
function refreshFrom(res: APIResponse): string {
  const raw = res.headersArray().filter((h) => h.name.toLowerCase() === "set-cookie").map((h) => h.value);
  for (const c of raw) {
    const m = /aasan_refresh=([^;]+)/.exec(c);
    if (m) return m[1];
  }
  throw new Error("no refresh cookie in auth response");
}

/**
 * POST to a throttled auth endpoint. The API allows 20 auth calls/min per IP; when it says 429, wait for
 * Retry-After and try again (we never loosen the throttle for tests).
 */
async function authPost(ctx: APIRequestContext, path: string, data: unknown): Promise<APIResponse> {
  for (let attempt = 0; ; attempt++) {
    let res: APIResponse;
    try {
      res = await ctx.post(path, { data });
    } catch (e) {
      if (attempt < 10 && /ECONNREFUSED|ECONNRESET|socket hang up/.test(String(e))) { // dev server reloading
        await sleep(2000);
        continue;
      }
      throw e;
    }
    if (res.status() === 500 && attempt < 4 && /database is locked/.test(await res.text())) {
      await sleep(500);
      continue;
    }
    if (res.status() !== 429 || attempt > 12) return res;
    const wait = Number(res.headers()["retry-after"] ?? "5");
    await sleep(Math.min(Math.max(wait, 1), 65) * 1000 + Math.random() * 500);
  }
}

let shared: APIRequestContext | null = null;
async function anon() {
  shared ??= await request.newContext({ baseURL: API_URL });
  return shared;
}

export async function registerUser(opts: { name?: string; tag?: string; email?: string; password?: string } = {}): Promise<TestUser> {
  const ctx = await anon();
  const email = opts.email ?? uniqueEmail(opts.tag);
  const password = opts.password ?? strongPassword();
  const name = opts.name ?? "E2E Learner";
  const res = await authPost(ctx, "/api/users/register/", { email, password, display_name: name, language: "en", accept_terms: true, age_band: "adult" });
  if (res.status() !== 201) throw new Error(`register ${res.status()}: ${await res.text()}`);
  const body = await res.json();
  return { email, password, name, id: body.user.id, access: body.access, refresh: refreshFrom(res) };
}

/** A fresh sign-in for an existing account (new refresh token; tokens rotate and are single-use). */
export async function loginUser(email: string, password: string): Promise<TestUser> {
  const ctx = await anon();
  const res = await authPost(ctx, "/api/users/login/", { email, password });
  if (res.status() !== 200) throw new Error(`login ${res.status()}: ${await res.text()}`);
  const body = await res.json();
  return { email, password, name: body.user.profile?.display_name ?? "", id: body.user.id, access: body.access, refresh: refreshFrom(res) };
}

/** Bearer-authenticated JSON client for setting up state through the real API. */
export class Api {
  constructor(private ctx: APIRequestContext, public token: string) {}

  static async as(user: { access: string }) {
    return new Api(await request.newContext({ baseURL: API_URL }), user.access);
  }

  private headers() {
    return { Authorization: `Bearer ${this.token}` };
  }

  private async unwrap<T>(method: string, path: string, res: APIResponse): Promise<T> {
    if (!res.ok()) throw new Error(`${method} ${path} → ${res.status()}: ${(await res.text()).slice(0, 500)}`);
    if (res.status() === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  /**
   * Setup calls retry the dev-SQLite "database is locked" 500 (the failed transaction rolled back, so a retry is safe)
   * and a dev-server reload (connection refused); anything else surfaces immediately.
   */
  private async send<T>(method: string, path: string, data?: unknown): Promise<T> {
    for (let attempt = 0; ; attempt++) {
      let res: APIResponse;
      try {
        res = await this.ctx.fetch(path, { method, headers: this.headers(), data: method === "GET" || method === "DELETE" ? undefined : (data ?? {}) });
      } catch (e) {
        if (attempt < 10 && /ECONNREFUSED|ECONNRESET|socket hang up/.test(String(e))) {
          await sleep(2000);
          continue;
        }
        throw e;
      }
      if (res.status() === 500 && attempt < 4 && /database is locked/.test(await res.text())) {
        await sleep(400 * (attempt + 1));
        continue;
      }
      return this.unwrap<T>(method, path, res);
    }
  }

  get<T = any>(path: string): Promise<T> {
    return this.send<T>("GET", path);
  }
  post<T = any>(path: string, data?: unknown): Promise<T> {
    return this.send<T>("POST", path, data);
  }
  patch<T = any>(path: string, data: unknown): Promise<T> {
    return this.send<T>("PATCH", path, data);
  }
  put<T = any>(path: string, data: unknown): Promise<T> {
    return this.send<T>("PUT", path, data);
  }
  delete(path: string) {
    return this.send("DELETE", path);
  }
  /** Raw response, for asserting statuses. */
  raw(method: "GET" | "POST" | "PATCH" | "DELETE", path: string, data?: unknown) {
    return this.ctx.fetch(path, { method, headers: this.headers(), data });
  }
}

/** Skip the onboarding wizard and first-visit tours for a fresh account (the onboarding spec covers the wizard). */
export async function completeOnboarding(api: Api) {
  await api.patch("/api/users/preferences/", { learning: { tours_done: ["app", "lab", "cockpit", "admin"] } });
  await api.patch("/api/users/profile/", { domain: "ai", level: "beginner", goals: ["Learn the basics of AI"], onboarding_completed: true });
}

const API_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "../../../api");

/**
 * Runs a short Django snippet for state the public API can't create (e.g. marking an inbox as verified, since the
 * test can't open the email). Arguments go through env vars (E2E_ARG_*), never the command line.
 */
export function django(script: string, args: Record<string, string | number> = {}): string {
  const env: Record<string, string> = { ...process.env } as Record<string, string>;
  for (const [k, v] of Object.entries(args)) env[`E2E_ARG_${k.toUpperCase()}`] = String(v);
  return execFileSync("uv", ["run", "python", "manage.py", "shell", "--no-imports", "-c", script], { cwd: API_DIR, env, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] }).trim();
}

export function verifyEmail(email: string) {
  django("import os\nfrom apps.accounts.models import User\nUser.objects.filter(email=os.environ['E2E_ARG_EMAIL']).update(email_verified=True)", { email });
}
