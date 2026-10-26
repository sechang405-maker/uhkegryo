import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(new URL("../components/AuthAccessControl.jsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");

test("root workspace exposes login and logout without changing local mode", () => {
  assert.match(page, /<AuthAccessControl\s*\/>/);
  assert.match(source, /response\.status === 404/);
  assert.match(source, /href="\/api\/auth\/google\/start"/);
  assert.match(source, /x-auth-action": "logout"/);
});

test("invite-required state leaves the workspace for the registration screen", () => {
  assert.match(source, /next\.state === "invite_required"/);
  assert.match(source, /window\.location\.replace\("\/invite"\)/);
});
