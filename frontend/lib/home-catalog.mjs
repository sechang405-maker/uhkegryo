import catalogIndex from "../../docs/domains/illustration-reference/term-cards/index.json" with { type: "json" };
import bodyCatalog from "../../docs/domains/illustration-reference/term-cards/body.json" with { type: "json" };
import poseCatalog from "../../docs/domains/illustration-reference/term-cards/pose.json" with { type: "json" };
import compositionCatalog from "../../docs/domains/illustration-reference/term-cards/composition.json" with { type: "json" };
import perspectiveCatalog from "../../docs/domains/illustration-reference/term-cards/perspective.json" with { type: "json" };

const HOME_TERM_IDS = [
  "body_hourglass", "body_inverted_triangle", "body_triangle",
  "body_slim", "body_childlike", "body_human_proportion",
  "pose_contrapposto", "pose_weight_shift", "pose_s_curve",
  "pose_standing", "pose_sitting", "pose_gesture", "pose_reclining", "pose_kneeling",
  "pose_walking", "pose_running", "pose_jumping", "pose_hand_open_palm",
  "view_front", "view_three_quarter", "view_high_angle",
  "view_low_angle", "view_profile", "view_back", "view_birds_eye", "view_worms_eye",
  "view_dutch_angle", "view_over_the_shoulder", "view_full_body",
  "perspective_three_point", "perspective_foreshortening", "perspective_vanishing_point",
  "perspective_one_point", "perspective_two_point",
  "composition_rule_of_thirds", "layout_composition",
];
const cardsById = new Map(
  [bodyCatalog, poseCatalog, compositionCatalog, perspectiveCatalog]
    .flatMap((catalog) => catalog.cards).map((card) => [card.term_id, card]),
);

// 검수된 홈 탐색 예시이며 LLM 선택·답변·이미지 검색 결과가 아닙니다.
export function catalogTerm(termId) {
  const card = cardsById.get(termId);
  const feedback = catalogIndex.active_term_feedback[termId];
  if (!card?.runtime_eligible || card.mvp_status !== "active_in_current_contract" || !feedback) {
    throw new Error(`검수 완료 TERM_CARD를 찾을 수 없습니다: ${termId}`);
  }
  return {
    role: card.role, term_id: card.term_id, label_ko: card.label_ko,
    plain_meaning_ko: feedback.plain_meaning_ko, selection_reason: null,
    reference_checkpoints: feedback.reference_checkpoints_ko,
    cautions: feedback.common_confusion_ko || [],
    recommended_search_query: [...card.query_fragments, "drawing"].join(" "),
    pins: [],
  };
}

export const HOME_TERMS = HOME_TERM_IDS.map(catalogTerm);

