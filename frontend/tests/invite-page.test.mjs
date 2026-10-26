import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/invite/page.jsx", import.meta.url), "utf8");

test("invite page keeps login and one-time redemption as separate states", () => {
  assert.match(page, /body\.state === "authenticated"/);
  assert.match(page, /state === "invite_required"/);
  assert.match(page, /href="\/api\/auth\/google\/start"/);
  assert.match(page, /"x-auth-action": "redeem"/);
  assert.match(page, /credentials: "include"/);
  assert.match(page, /disabled=\{submitting\}/);
  assert.doesNotMatch(page, /client_secret|google_subject|account_id/);
});
