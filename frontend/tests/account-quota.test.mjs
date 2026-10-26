import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const source = fs.readFileSync(new URL("../components/AccountQuota.jsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../app/page.jsx", import.meta.url), "utf8");
const creator = fs.readFileSync(new URL("../components/PersonalTermCreator.jsx", import.meta.url), "utf8");

test("account quota distinguishes cumulative, charged, reserved, and available units", () => {
  assert.match(source, /\/api\/account\/usage/);
  assert.match(source, /누적 지급/);
  assert.match(source, /사용 완료/);
  assert.match(source, /처리 중/);
  assert.match(source, /이용 가능/);
  assert.match(source, /고정 안내와 이미지 재검색은 차감되지 않습니다/);
});

test("successful AI paths refresh account quota without resetting conversations", () => {
  assert.match(page, /account-quota-refresh/);
  assert.match(creator, /account-quota-refresh/);
  assert.match(page, /<AccountQuota\s*\/>/);
});
