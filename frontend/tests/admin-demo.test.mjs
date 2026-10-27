import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const page = fs.readFileSync(new URL("../app/admin/page.jsx", import.meta.url), "utf8");

test("admin page protects mutations and confirms important changes", () => {
  assert.match(page, /\/api\/admin\/demo/);
  assert.match(page, /x-admin-action/);
  assert.match(page, /window\.confirm/);
  assert.match(page, /기존값/);
  assert.match(page, /새 값/);
});

test("invite code is shown only from the issuance response", () => {
  assert.match(page, /raw_code/);
  assert.match(page, /한 번만 표시/);
  assert.match(page, /미사용 초대 폐기/);
  assert.doesNotMatch(page, /client_secret|google_subject/);
});

test("admin account table distinguishes unlimited from finite limits", () => {
  assert.match(page, /account\.usage\.unlimited/);
  assert.match(page, /무제한/);
});
