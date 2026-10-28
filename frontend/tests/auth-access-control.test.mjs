import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { readAuthState } from "../lib/auth-state.mjs";

const source = fs.readFileSync(new URL("../components/AuthAccessControl.jsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");

test("root workspace exposes login and logout while local mode stays hidden on auth 404", async () => {
  let request;
  const result = await readAuthState({ fetchImpl: async (...args) => {
    request = args;
    return { ok: false, status: 404 };
  } });
  assert.equal(result, null);
  assert.equal(request[0], "/api/auth/me");
  assert.equal(request[1].credentials, "include");
  assert.equal(request[1].cache, "no-store");
  assert.match(page, /<AuthAccessControl\s*\/>/);
  assert.match(source, /href="\/api\/auth\/google\/start"/);
  assert.match(source, /x-auth-action": "logout"/);
});

test("invite-required state leaves the workspace for the registration screen", () => {
  assert.match(source, /next\.state === "invite_required"/);
  assert.match(source, /window\.location\.replace\("\/invite"\)/);
});

test("auth state is refreshed after login navigation restores or reactivates the page", () => {
  assert.match(source, /window\.addEventListener\("pageshow", onPageShow\)/);
  assert.match(source, /window\.addEventListener\("focus", onFocus\)/);
  assert.match(source, /document\.addEventListener\("visibilitychange", onVisible\)/);
  assert.match(source, /document\.visibilityState === "visible"/);
});
