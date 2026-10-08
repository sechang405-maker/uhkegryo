import test from "node:test";
import assert from "node:assert/strict";
import { createMindMapSlots, firstSelectableTermId } from "../lib/term-mind-map.mjs";

test("AC-10: 역할 순서의 5개 방사형 위치를 만들고 없는 역할은 비활성으로 둔다", () => {
  const slots = createMindMapSlots([
    { role: "perspective", term_id: "perspective_low", label_ko: "로우 앵글" },
    { role: "pose", term_id: "pose_contrapposto", label_ko: "콘트라포스토" },
  ]);

  assert.deepEqual(slots.map((slot) => slot.role), ["body", "pose", "view", "perspective", "layout"]);
  assert.equal(slots[0].term, null);
  assert.equal(slots[1].term.label_ko, "콘트라포스토");
  assert.equal(slots[3].term.label_ko, "로우 앵글");
  assert.deepEqual(slots[1].terms.map((term) => term.term_id), ["pose_contrapposto"]);
  assert.equal(firstSelectableTermId(slots), "pose_contrapposto");
});

test("같은 역할의 TERM_CARD도 미리보기용 그룹에서 원래 순서로 유지한다", () => {
  const slots = createMindMapSlots([
    { role: "body", term_id: "body_hourglass", label_ko: "모래시계형" },
    { role: "body", term_id: "body_triangle", label_ko: "삼각형" },
  ]);

  assert.deepEqual(slots[0].terms.map((term) => term.term_id), ["body_hourglass", "body_triangle"]);
  assert.equal(firstSelectableTermId(slots), "body_hourglass");
});

test("AC-10: 유효하지 않거나 알 수 없는 TERM_CARD는 선택 버튼으로 만들지 않는다", () => {
  const slots = createMindMapSlots([
    { role: "unknown", term_id: "unknown_card", label_ko: "알 수 없음" },
    { role: "body", term_id: "", label_ko: "체형" },
  ]);

  assert.equal(slots.every((slot) => slot.term === null), true);
  assert.equal(firstSelectableTermId(slots), null);
});
