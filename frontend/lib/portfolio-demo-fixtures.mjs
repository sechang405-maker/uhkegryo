import { HOME_TERMS, catalogTerm } from './home-catalog.mjs';

// Original sample prose using the project's reviewed TERM_CARD catalog.
// No third-party image, thumbnail, remote response or real user data is bundled.
const samples = [
  ['demo-hourglass', '어깨와 골반 폭이 비슷하고 허리가 들어간 캐릭터', ['body_hourglass'],
    '샘플 답변: 어깨와 골반 폭이 비슷하고 허리가 들어간 실루엣을 모래시계형으로 설명합니다. 포즈와 구도는 이 예시에서 정하지 않았습니다.'],
  ['demo-weight-shift', '한쪽 다리에 체중을 싣고 선 캐릭터', ['pose_weight_shift'],
    '샘플 답변: 한쪽 다리에 체중을 싣는 자세를 체중 이동으로 설명합니다. 어깨와 골반의 반대 기울기는 지정되지 않았으므로 콘트라포스토로 단정하지 않습니다.'],
  ['demo-seated-low', '아래에서 올려다보는 앉은 캐릭터', ['pose_sitting', 'view_low_angle'],
    '샘플 답변: 앉은 자세와 아래에서 올려다보는 낮은 구도를 함께 보여 줍니다. 신체 단축이나 배경 투시는 별도로 지정하지 않았습니다.'],
];
export const DEMO_SCENARIOS = samples.map(([id, request, ids, answer]) => ({
  id, request, job: { job_status: 'completed', result: { agent_status: 'success',
    answer_text: answer + '\n\n※ 고정 샘플입니다. 실제 AI 생성과 실시간 이미지 검색을 실행하지 않습니다.',
    reference_plan: { terms: ids.map(catalogTerm) },
  } },
}));
export const DEMO_NOTICE = '샘플 데모 · 실제 AI 및 검색 미연결';
export const DEMO_INPUT_ERROR = '샘플에 없는 입력입니다. 대표 예시를 선택해 주세요.';
export function matchDemoScenario(text) {
  return DEMO_SCENARIOS.find(item => item.request === text.trim()) || null;
}
export function demoTerm(id) {
  return [...HOME_TERMS, ...DEMO_SCENARIOS.flatMap(s => s.job.result.reference_plan.terms)]
    .find(term => term.term_id === id) || null;
}
