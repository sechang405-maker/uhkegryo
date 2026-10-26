import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const root = path.resolve(import.meta.dirname, "..");
const admin = fs.readFileSync(path.join(root, "app/admin/page.jsx"), "utf8");
const transferPath = path.join(root, "app/transfer/page.jsx");
const transfer = fs.existsSync(transferPath) ? fs.readFileSync(transferPath, "utf8") : "";
const quota = fs.readFileSync(path.join(root, "components/AccountQuota.jsx"), "utf8");

test("verified Google identity transfer is requested by the account and approved by an admin", () => {
  assert.match(transfer, /\/api\/auth\/identity-transfer\/request/);
  assert.match(transfer, /x-auth-action[^\n]+request-transfer/);
  assert.match(admin, /approve-transfer/);
  assert.match(admin, /reject-transfer/);
  assert.match(admin, /target_email/);
  assert.match(admin, /path\.includes\("\/transfers\/"\) \? "POST"/);
});

test("account transfer never asks an administrator to type a Google subject", () => {
  assert.doesNotMatch(admin, /google_subject/);
  assert.match(quota, /Google 계정 변경/);
  assert.match(quota, /\/api\/auth\/google\/start/);
});
